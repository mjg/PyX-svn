# -*- encoding: utf-8 -*-
#
#
# Copyright (C) 2002-2004 Jörg Lehmann <joergl@users.sourceforge.net>
# Copyright (C) 2003-2011 Michael Schindler <m-schindler@users.sourceforge.net>
# Copyright (C) 2002-2011 André Wobst <wobsta@users.sourceforge.net>
#
# This file is part of PyX (http://pyx.sourceforge.net/).
#
# PyX is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# PyX is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PyX; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA

import errno, functools, glob, os, threading, queue, re, tempfile, atexit, time, warnings
from . import config, unit, box, canvas, trafo, version, attr, style, pycompat, path
from pyx.dvi import dvifile
from . import bbox as bboxmodule

class PyXTeXWarning(UserWarning): pass
warnings.filterwarnings("always", category=PyXTeXWarning)

###############################################################################
# texmessages
# - please don't get confused:
#   - there is a texmessage (and a texmessageparsed) attribute within the
#     texrunner; it contains TeX/LaTeX response from the last command execution
#   - instances of classes derived from the class texmessage are used to
#     parse the TeX/LaTeX response as it is stored in the texmessageparsed
#     attribute of a texrunner instance
#   - the multiple usage of the name texmessage might be removed in the future
# - texmessage instances should implement _Itexmessage
###############################################################################

class TexResultError(RuntimeError):
    """specialized texrunner exception class
    - it is raised by texmessage instances, when a texmessage indicates an error
    - it is raised by the texrunner itself, whenever there is a texmessage left
      after all parsing of this message (by texmessage instances)
    prints a detailed report about the problem
    - the verbose level is controlled by texrunner.errordebug"""

    def __init__(self, description, texrunner):
        if texrunner.errordebug >= 2:
            self.description = ("%s\n" % description +
                                "The expression passed to TeX was:\n"
                                "  %s\n" % texrunner.expr.replace("\n", "\n  ").rstrip() +
                                "The return message from TeX was:\n"
                                "  %s\n" % texrunner.texmessage.replace("\n", "\n  ").rstrip() +
                                "After parsing this message, the following was left:\n"
                                "  %s" % texrunner.texmessageparsed.replace("\n", "\n  ").rstrip())
        elif texrunner.errordebug == 1:
            firstlines = texrunner.texmessageparsed.split("\n")
            if len(firstlines) > 5:
                firstlines = firstlines[:5] + ["(cut after 5 lines, increase errordebug for more output)"]
            self.description = ("%s\n" % description +
                                "The expression passed to TeX was:\n"
                                "  %s\n" % texrunner.expr.replace("\n", "\n  ").rstrip() +
                                "After parsing the return message from TeX, the following was left:\n" +
                                functools.reduce(lambda x, y: "%s  %s\n" % (x,y), firstlines, "").rstrip())
        else:
            self.description = description

    def __str__(self):
        return self.description


class _Itexmessage:
    """validates/invalidates TeX/LaTeX response"""

    def check(self, texrunner):
        """check a Tex/LaTeX response and respond appropriate
        - read the texrunners texmessageparsed attribute
        - if there is an problem found, raise TexResultError
        - remove any valid and identified TeX/LaTeX response
          from the texrunners texmessageparsed attribute
          -> finally, there should be nothing left in there,
             otherwise it is interpreted as an error"""


class texmessage(attr.attr): pass


class _texmessagestart(texmessage):
    """validates TeX/LaTeX startup"""

    __implements__ = _Itexmessage

    startpattern = re.compile(r"This is [-0-9a-zA-Z\s_]*TeX")

    def check(self, texrunner):
        # check for "This is e-TeX"
        m = self.startpattern.search(texrunner.texmessageparsed)
        if not m:
            raise TexResultError("TeX startup failed", texrunner)
        texrunner.texmessageparsed = texrunner.texmessageparsed[m.end():]

        # check for \raiseerror -- just to be sure that communication works
        try:
            texrunner.texmessageparsed = texrunner.texmessageparsed.split("*! Undefined control sequence.\n<*> \\raiseerror\n               %\n", 1)[1]
        except (IndexError, ValueError):
            raise TexResultError("TeX scrollmode check failed", texrunner)


class _texmessagenofile(texmessage):
    """allows for LaTeXs no-file warning"""

    __implements__ = _Itexmessage

    def __init__(self, fileending):
        self.fileending = fileending

    def check(self, texrunner):
        try:
            s1, s2 = texrunner.texmessageparsed.split("No file %s.%s." % (texrunner.texfilename, self.fileending), 1)
            texrunner.texmessageparsed = s1 + s2
        except (IndexError, ValueError):
            try:
                s1, s2 = texrunner.texmessageparsed.split("No file %s%s%s.%s." % (os.curdir,
                                                                                   os.sep,
                                                                                   texrunner.texfilename,
                                                                                   self.fileending), 1)
                texrunner.texmessageparsed = s1 + s2
            except (IndexError, ValueError):
                pass


class _texmessageinputmarker(texmessage):
    """validates the PyXInputMarker"""

    __implements__ = _Itexmessage

    def check(self, texrunner):
        try:
            s1, s2 = texrunner.texmessageparsed.split("PyXInputMarker:executeid=%s:" % texrunner.executeid, 1)
            texrunner.texmessageparsed = s1 + s2
        except (IndexError, ValueError):
            raise TexResultError("PyXInputMarker expected", texrunner)


class _texmessagepyxbox(texmessage):
    """validates the PyXBox output"""

    __implements__ = _Itexmessage

    pattern = re.compile(r"PyXBox:page=(?P<page>\d+),lt=-?\d*((\d\.?)|(\.?\d))\d*pt,rt=-?\d*((\d\.?)|(\.?\d))\d*pt,ht=-?\d*((\d\.?)|(\.?\d))\d*pt,dp=-?\d*((\d\.?)|(\.?\d))\d*pt:")

    def check(self, texrunner):
        m = self.pattern.search(texrunner.texmessageparsed)
        if m and m.group("page") == str(texrunner.page):
            texrunner.texmessageparsed = texrunner.texmessageparsed[:m.start()] + texrunner.texmessageparsed[m.end():]
        else:
            raise TexResultError("PyXBox expected", texrunner)


class _texmessagepyxpageout(texmessage):
    """validates the dvi shipout message (writing a page to the dvi file)"""

    __implements__ = _Itexmessage

    def check(self, texrunner):
        try:
            s1, s2 = texrunner.texmessageparsed.split("[80.121.88.%s]" % texrunner.page, 1)
            texrunner.texmessageparsed = s1 + s2
        except (IndexError, ValueError):
            raise TexResultError("PyXPageOutMarker expected", texrunner)


class _texmessageend(texmessage):
    """validates TeX/LaTeX finish"""

    __implements__ = _Itexmessage

    auxPattern = re.compile(r"\(([^()]+\.aux|\"[^\"]+\.aux\")\)")

    def check(self, texrunner):
        m = self.auxPattern.search(texrunner.texmessageparsed)
        if m:
            texrunner.texmessageparsed = (texrunner.texmessageparsed[:m.start()] + texrunner.texmessageparsed[m.end():]).strip()

        # check for "(see the transcript file for additional information)"
        try:
            s1, s2 = texrunner.texmessageparsed.split("(see the transcript file for additional information)", 1)
            texrunner.texmessageparsed = (s1 + s2).strip()
        except (IndexError, ValueError):
            pass

        # check for "Output written on ...dvi (1 page, 220 bytes)."
        dvipattern = re.compile(r"Output written on %s\.dvi \((?P<page>\d+) pages?, \d+ bytes\)\." % texrunner.texfilename)
        m = dvipattern.search(texrunner.texmessageparsed)
        if texrunner.page:
            if not m:
                raise TexResultError("TeX dvifile messages expected", texrunner)
            if m.group("page") != str(texrunner.page):
                raise TexResultError("wrong number of pages reported", texrunner)
            texrunner.texmessageparsed = texrunner.texmessageparsed[:m.start()] + texrunner.texmessageparsed[m.end():]
        else:
            try:
                s1, s2 = texrunner.texmessageparsed.split("No pages of output.", 1)
                texrunner.texmessageparsed = s1 + s2
            except (IndexError, ValueError):
                raise TexResultError("no dvifile expected", texrunner)

        # check for "Transcript written on ...log."
        try:
            s1, s2 = texrunner.texmessageparsed.split("Transcript written on %s.log." % texrunner.texfilename, 1)
            texrunner.texmessageparsed = s1 + s2
        except (IndexError, ValueError):
            raise TexResultError("TeX logfile message expected", texrunner)


class _texmessageemptylines(texmessage):
    """validates "*-only" (TeX/LaTeX input marker in interactive mode) and empty lines
    also clear TeX interactive mode warning (Please type a command or say `\\end')
    """

    __implements__ = _Itexmessage

    def check(self, texrunner):
        texrunner.texmessageparsed = texrunner.texmessageparsed.replace(r"(Please type a command or say `\end')", "")
        texrunner.texmessageparsed = texrunner.texmessageparsed.replace(" ", "")
        texrunner.texmessageparsed = texrunner.texmessageparsed.replace("*\n", "")
        texrunner.texmessageparsed = texrunner.texmessageparsed.replace("\n", "")


class _texmessageload(texmessage):
    """validates inclusion of arbitrary files
    - the matched pattern is "(<filename> <arbitrary other stuff>)", where
      <filename> is a readable file and other stuff can be anything
    - If the filename is enclosed in double quotes, it may contain blank space.
    - "(" and ")" must be used consistent (otherwise this validator just does nothing)
    - this is not always wanted, but we just assume that file inclusion is fine"""

    __implements__ = _Itexmessage

    pattern = re.compile(r"\([\"]?(?P<filename>(?:(?<!\")[^()\s\n]+(?!\"))|[^\"\n]+)[\"]?(?P<additional>[^()]*)\)")

    def baselevels(self, s, maxlevel=1, brackets="()", quotes='""'):
        """strip parts of a string above a given bracket level
        - return a modified (some parts might be removed) version of the string s
          where all parts inside brackets with level higher than maxlevel are
          removed
        - if brackets do not match (number of left and right brackets is wrong
          or at some points there were more right brackets than left brackets)
          just return the unmodified string
        - a quoted string immediately followed after a bracket is left untouched
          even if it contains quotes itself"""
        level = 0
        highestlevel = 0
        inquote = 0
        res = ""
        for i, c in enumerate(s):
            if quotes and level <= maxlevel:
                if not inquote and c == quotes[0] and i and s[i-1] == brackets[0]:
                    inquote = 1
                elif inquote and c == quotes[1]:
                    inquote = 0
            if inquote:
                res += c
            else:
                if c == brackets[0]:
                    level += 1
                    if level > highestlevel:
                        highestlevel = level
                if level <= maxlevel:
                    res += c
                if c == brackets[1]:
                    level -= 1
        if level == 0 and highestlevel > 0:
            return res

    def check(self, texrunner):
        search = self.baselevels(texrunner.texmessageparsed)
        res = []
        if search is not None:
            m = self.pattern.search(search)
            while m:
                filename = m.group("filename").replace("\n", "")
                try:
                    additional = m.group("additional")
                except IndexError:
                    additional = ""
                if (os.access(filename, os.R_OK) or
                    len(additional) and additional[0] == "\n" and os.access(filename+additional.split()[0], os.R_OK)):
                    res.append(search[:m.start()])
                else:
                    res.append(search[:m.end()])
                search = search[m.end():]
                m = self.pattern.search(search)
            else:
                res.append(search)
                texrunner.texmessageparsed = "".join(res)


class _texmessageloaddef(_texmessageload):
    """validates the inclusion of font description files (fd-files)
    - works like _texmessageload
    - filename must end with .def or .fd
    - further text is allowed"""

    pattern = re.compile(r"\([\"]?(?P<filename>(?:(?:(?<!\")[^\(\)\s\n\"]+)|(?:(?<=\")[^\(\)\"]+))(\.fd|\.def))[\"]?[\s\n]*(?P<additional>[\(]?[^\(\)]*[\)]?)[\s\n]*\)")

    def baselevels(self, s, **kwargs):
        return s


class _texmessagegraphicsload(_texmessageload):
    """validates the inclusion of files as the graphics packages writes it
    - works like _texmessageload, but using "<" and ">" as delimiters
    - filename must end with .eps and no further text is allowed"""

    pattern = re.compile(r"<(?P<filename>[^>]+.eps)>")

    def baselevels(self, s, **kwargs):
        return s


class _texmessageignore(_texmessageload):
    """validates any TeX/LaTeX response
    - this might be used, when the expression is ok, but no suitable texmessage
      parser is available
    - PLEASE: - consider writing suitable tex message parsers
              - share your ideas/problems/solutions with others (use the PyX mailing lists)"""

    __implements__ = _Itexmessage

    def check(self, texrunner):
        texrunner.texmessageparsed = ""


texmessage.start = _texmessagestart()
texmessage.noaux = _texmessagenofile("aux")
texmessage.nonav = _texmessagenofile("nav")
texmessage.end = _texmessageend()
texmessage.load = _texmessageload()
texmessage.loaddef = _texmessageloaddef()
texmessage.graphicsload = _texmessagegraphicsload()
texmessage.ignore = _texmessageignore()

# for internal use:
texmessage.inputmarker = _texmessageinputmarker()
texmessage.pyxbox = _texmessagepyxbox()
texmessage.pyxpageout = _texmessagepyxpageout()
texmessage.emptylines = _texmessageemptylines()


class _texmessageallwarning(texmessage):
    """validates a given pattern 'pattern' as a warning 'warning'"""

    def check(self, texrunner):
        if texrunner.texmessageparsed:
            warnings.warn("ignoring all warnings:\n%s" % texrunner.texmessageparsed)
        texrunner.texmessageparsed = ""

texmessage.allwarning = _texmessageallwarning()


class texmessagepattern(texmessage):
    """validates a given pattern and issue a warning (when set)"""

    def __init__(self, pattern, warning=None):
        self.pattern = pattern
        self.warning = warning

    def check(self, texrunner):
        m = self.pattern.search(texrunner.texmessageparsed)
        while m:
            texrunner.texmessageparsed = texrunner.texmessageparsed[:m.start()] + texrunner.texmessageparsed[m.end():]
            if self.warning:
                warnings.warn("%s:\n%s" % (self.warning, m.string[m.start(): m.end()].rstrip()))
            m = self.pattern.search(texrunner.texmessageparsed)

texmessage.fontwarning = texmessagepattern(re.compile(r"^LaTeX Font Warning: .*$(\n^\(Font\).*$)*", re.MULTILINE), "ignoring font warning")
texmessage.boxwarning = texmessagepattern(re.compile(r"^(Overfull|Underfull) \\[hv]box.*$(\n^..*$)*\n^$\n", re.MULTILINE), "ignoring overfull/underfull box warning")
texmessage.rerunwarning = texmessagepattern(re.compile(r"^(LaTeX Warning: Label\(s\) may have changed\. Rerun to get cross-references right\s*\.)$", re.MULTILINE), "ignoring rerun warning")
texmessage.packagewarning = texmessagepattern(re.compile(r"^package\s+(?P<packagename>\S+)\s+warning\s*:[^\n]+(?:\n\(?(?P=packagename)\)?[^\n]*)*", re.MULTILINE | re.IGNORECASE), "ignoring generic package warning")
texmessage.nobblwarning = texmessagepattern(re.compile(r"^[\s\*]*(No file .*\.bbl.)\s*", re.MULTILINE), "ignoring no-bbl warning")



###############################################################################
# textattrs
###############################################################################

_textattrspreamble = ""

class textattr:
    "a textattr defines a apply method, which modifies a (La)TeX expression"

class _localattr: pass

_textattrspreamble += r"""\gdef\PyXFlushHAlign{0}%
\def\PyXragged{%
\leftskip=0pt plus \PyXFlushHAlign fil%
\rightskip=0pt plus 1fil%
\advance\rightskip0pt plus -\PyXFlushHAlign fil%
\parfillskip=0pt%
\pretolerance=9999%
\tolerance=9999%
\parindent=0pt%
\hyphenpenalty=9999%
\exhyphenpenalty=9999}%
"""

class boxhalign(attr.exclusiveattr, textattr, _localattr):

    def __init__(self, aboxhalign):
        self.boxhalign = aboxhalign
        attr.exclusiveattr.__init__(self, boxhalign)

    def apply(self, expr):
        return r"\gdef\PyXBoxHAlign{%.5f}%s" % (self.boxhalign, expr)

boxhalign.left = boxhalign(0)
boxhalign.center = boxhalign(0.5)
boxhalign.right = boxhalign(1)
# boxhalign.clear = attr.clearclass(boxhalign) # we can't defined a clearclass for boxhalign since it can't clear a halign's boxhalign


class flushhalign(attr.exclusiveattr, textattr, _localattr):

    def __init__(self, aflushhalign):
        self.flushhalign = aflushhalign
        attr.exclusiveattr.__init__(self, flushhalign)

    def apply(self, expr):
        return r"\gdef\PyXFlushHAlign{%.5f}\PyXragged{}%s" % (self.flushhalign, expr)

flushhalign.left = flushhalign(0)
flushhalign.center = flushhalign(0.5)
flushhalign.right = flushhalign(1)
# flushhalign.clear = attr.clearclass(flushhalign) # we can't defined a clearclass for flushhalign since it couldn't clear a halign's flushhalign


class halign(boxhalign, flushhalign, _localattr):

    def __init__(self, aboxhalign, aflushhalign):
        self.boxhalign = aboxhalign
        self.flushhalign = aflushhalign
        attr.exclusiveattr.__init__(self, halign)

    def apply(self, expr):
        return r"\gdef\PyXBoxHAlign{%.5f}\gdef\PyXFlushHAlign{%.5f}\PyXragged{}%s" % (self.boxhalign, self.flushhalign, expr)

halign.left = halign(0, 0)
halign.center = halign(0.5, 0.5)
halign.right = halign(1, 1)
halign.clear = attr.clearclass(halign)
halign.boxleft = boxhalign.left
halign.boxcenter = boxhalign.center
halign.boxright = boxhalign.right
halign.flushleft = halign.raggedright = flushhalign.left
halign.flushcenter = halign.raggedcenter = flushhalign.center
halign.flushright = halign.raggedleft = flushhalign.right


class _mathmode(attr.attr, textattr, _localattr):
    "math mode"

    def apply(self, expr):
        return r"$\displaystyle{%s}$" % expr

mathmode = _mathmode()
clearmathmode = attr.clearclass(_mathmode)


class _phantom(attr.attr, textattr, _localattr):
    "phantom text"

    def apply(self, expr):
        return r"\phantom{%s}" % expr

phantom = _phantom()
clearphantom = attr.clearclass(_phantom)


_textattrspreamble += "\\newbox\\PyXBoxVBox%\n\\newdimen\\PyXDimenVBox%\n"

class parbox_pt(attr.sortbeforeexclusiveattr, textattr):

    top = 1
    middle = 2
    bottom = 3

    def __init__(self, width, baseline=top):
        self.width = width * 72.27 / (unit.scale["x"] * 72)
        self.baseline = baseline
        attr.sortbeforeexclusiveattr.__init__(self, parbox_pt, [_localattr])

    def apply(self, expr):
        if self.baseline == self.top:
            return r"\linewidth=%.5ftruept\vtop{\hsize=\linewidth\textwidth=\linewidth{}%s}" % (self.width, expr)
        elif self.baseline == self.middle:
            return r"\linewidth=%.5ftruept\setbox\PyXBoxVBox=\hbox{{\vtop{\hsize=\linewidth\textwidth=\linewidth{}%s}}}\PyXDimenVBox=0.5\dp\PyXBoxVBox\setbox\PyXBoxVBox=\hbox{{\vbox{\hsize=\linewidth\textwidth=\linewidth{}%s}}}\advance\PyXDimenVBox by -0.5\dp\PyXBoxVBox\lower\PyXDimenVBox\box\PyXBoxVBox" % (self.width, expr, expr)
        elif self.baseline == self.bottom:
            return r"\linewidth=%.5ftruept\vbox{\hsize=\linewidth\textwidth=\linewidth{}%s}" % (self.width, expr)
        else:
            RuntimeError("invalid baseline argument")

parbox_pt.clear = attr.clearclass(parbox_pt)

class parbox(parbox_pt):

    def __init__(self, width, **kwargs):
        parbox_pt.__init__(self, unit.topt(width), **kwargs)

parbox.clear = parbox_pt.clear


_textattrspreamble += "\\newbox\\PyXBoxVAlign%\n\\newdimen\\PyXDimenVAlign%\n"

class valign(attr.sortbeforeexclusiveattr, textattr):

    def __init__(self, avalign):
        self.valign = avalign
        attr.sortbeforeexclusiveattr.__init__(self, valign, [parbox_pt, _localattr])

    def apply(self, expr):
        return r"\setbox\PyXBoxVAlign=\hbox{{%s}}\PyXDimenVAlign=%.5f\ht\PyXBoxVAlign\advance\PyXDimenVAlign by -%.5f\dp\PyXBoxVAlign\lower\PyXDimenVAlign\box\PyXBoxVAlign" % (expr, 1-self.valign, self.valign)

valign.top = valign(0)
valign.middle = valign(0.5)
valign.bottom = valign(1)
valign.clear = valign.baseline = attr.clearclass(valign)


_textattrspreamble += "\\newdimen\\PyXDimenVShift%\n"

class _vshift(attr.sortbeforeattr, textattr):

    def __init__(self):
        attr.sortbeforeattr.__init__(self, [valign, parbox_pt, _localattr])

    def apply(self, expr):
        return r"%s\setbox0\hbox{{%s}}\lower\PyXDimenVShift\box0" % (self.setheightexpr(), expr)

class vshift(_vshift):
    "vertical down shift by a fraction of a character height"

    def __init__(self, lowerratio, heightstr="0"):
        _vshift.__init__(self)
        self.lowerratio = lowerratio
        self.heightstr = heightstr

    def setheightexpr(self):
        return r"\setbox0\hbox{{%s}}\PyXDimenVShift=%.5f\ht0" % (self.heightstr, self.lowerratio)

class _vshiftmathaxis(_vshift):
    "vertical down shift by the height of the math axis"

    def setheightexpr(self):
        return r"\setbox0\hbox{$\vcenter{\vrule width0pt}$}\PyXDimenVShift=\ht0"


vshift.bottomzero = vshift(0)
vshift.middlezero = vshift(0.5)
vshift.topzero = vshift(1)
vshift.mathaxis = _vshiftmathaxis()
vshift.clear = attr.clearclass(_vshift)


defaultsizelist = ["normalsize", "large", "Large", "LARGE", "huge", "Huge",
None, "tiny", "scriptsize", "footnotesize", "small"]

class size(attr.sortbeforeattr, textattr):
    "font size"

    def __init__(self, sizeindex=None, sizename=None, sizelist=defaultsizelist):
        if (sizeindex is None and sizename is None) or (sizeindex is not None and sizename is not None):
            raise RuntimeError("either specify sizeindex or sizename")
        attr.sortbeforeattr.__init__(self, [_mathmode, _vshift])
        if sizeindex is not None:
            if sizeindex >= 0 and sizeindex < sizelist.index(None):
                self.size = sizelist[sizeindex]
            elif sizeindex < 0 and sizeindex + len(sizelist) > sizelist.index(None):
                self.size = sizelist[sizeindex]
            else:
                raise IndexError("index out of sizelist range")
        else:
            self.size = sizename

    def apply(self, expr):
        return r"\%s{}%s" % (self.size, expr)

size.tiny = size(-4)
size.scriptsize = size.script = size(-3)
size.footnotesize = size.footnote = size(-2)
size.small = size(-1)
size.normalsize = size.normal = size(0)
size.large = size(1)
size.Large = size(2)
size.LARGE = size(3)
size.huge = size(4)
size.Huge = size(5)
size.clear = attr.clearclass(size)


###############################################################################
# texrunner
###############################################################################


class _readpipe(threading.Thread):
    """threaded reader of TeX/LaTeX output
    - sets an event, when a specific string in the programs output is found
    - sets an event, when the terminal ends"""

    def __init__(self, pipe, expectqueue, gotevent, gotqueue, quitevent):
        """initialize the reader
        - pipe: file to be read from
        - expectqueue: keeps the next InputMarker to be wait for
        - gotevent: the "got InputMarker" event
        - gotqueue: a queue containing the lines recieved from TeX/LaTeX
        - quitevent: the "end of terminal" event"""
        threading.Thread.__init__(self)
        self.setDaemon(1) # don't care if the output might not be finished (nevertheless, it shouldn't happen)
        self.pipe = pipe
        self.expectqueue = expectqueue
        self.gotevent = gotevent
        self.gotqueue = gotqueue
        self.quitevent = quitevent
        self.expect = None

    def run(self):
        """thread routine"""
        def _read():
            # catch interupted system call errors while reading
            while 1:
                try:
                    return self.pipe.readline()
                except IOError as e:
                    if e.errno != errno.EINTR:
                         raise
        read = _read() # read, what comes in
        try:
            self.expect = self.expectqueue.get_nowait() # read, what should be expected
        except queue.Empty:
            pass
        while len(read):
            # universal EOL handling (convert everything into unix like EOLs)
            # XXX is this necessary on pipes?
            read = read.replace(b"\r", b"").replace(b"\n", b"") + b"\n"
            self.gotqueue.put(read) # report, whats read
            if self.expect is not None and read.find(self.expect) != -1:
                self.gotevent.set() # raise the got event, when the output was expected (XXX: within a single line)
            read = _read() # read again
            try:
                self.expect = self.expectqueue.get_nowait()
            except queue.Empty:
                pass
        # EOF reached
        self.pipe.close()
        if self.expect is not None and self.expect.find(b"PyXInputMarker") != -1:
            raise RuntimeError("TeX/LaTeX finished unexpectedly")
        self.quitevent.set()


class textbox(box.rect, canvas.canvas):
    """basically a box.rect, but it contains a text created by the texrunner
    - texrunner._text and texrunner.text return such an object
    - _textbox instances can be inserted into a canvas
    - the output is contained in a page of the dvifile available thru the texrunner"""
    # TODO: shouldn't all boxes become canvases? how about inserts then?

    def __init__(self, x, y, left, right, height, depth, finishdvi, attrs):
        """
        - finishdvi is a method to be called to get the dvicanvas
          (e.g. the finishdvi calls the setdvicanvas method)
        - attrs are fillstyles"""
        self.left = left
        self.right = right
        self.width = left + right
        self.height = height
        self.depth = depth
        self.texttrafo = trafo.scale(unit.scale["x"]).translated(x, y)
        box.rect.__init__(self, x - left, y - depth, left + right, depth + height, abscenter = (left, depth))
        canvas.canvas.__init__(self, attrs)
        self.finishdvi = finishdvi
        self.dvicanvas = None
        self.insertdvicanvas = 0

    def transform(self, *trafos):
        if self.insertdvicanvas:
            raise RuntimeError("can't apply transformation after dvicanvas was inserted")
        box.rect.transform(self, *trafos)
        for trafo in trafos:
            self.texttrafo = trafo * self.texttrafo

    def setdvicanvas(self, dvicanvas):
        if self.dvicanvas is not None:
            raise RuntimeError("multiple call to setdvicanvas")
        self.dvicanvas = dvicanvas

    def ensuredvicanvas(self):
        if self.dvicanvas is None:
            self.finishdvi()
            assert self.dvicanvas is not None, "finishdvi is broken"
        if not self.insertdvicanvas:
            self.insert(self.dvicanvas, [self.texttrafo])
            self.insertdvicanvas = 1

    def marker(self, marker):
        self.ensuredvicanvas()
        return self.texttrafo.apply(*self.dvicanvas.markers[marker])

    def textpath(self):
        self.ensuredvicanvas()
        textpath = path.path()
        for item in self.dvicanvas.items:
            try:
                textpath += item.textpath()
            except AttributeError:
                # ignore color settings etc.
                pass
        return textpath.transformed(self.texttrafo)

    def processPS(self, file, writer, context, registry, bbox):
        self.ensuredvicanvas()
        abbox = bboxmodule.empty()
        canvas.canvas.processPS(self, file, writer, context, registry, abbox)
        bbox += box.rect.bbox(self)

    def processPDF(self, file, writer, context, registry, bbox):
        self.ensuredvicanvas()
        abbox = bboxmodule.empty()
        canvas.canvas.processPDF(self, file, writer, context, registry, abbox)
        bbox += box.rect.bbox(self)


def _cleantmp(texrunner):
    """get rid of temporary files
    - function to be registered by atexit
    - files contained in usefiles are kept"""
    if texrunner.texruns: # cleanup while TeX is still running?
        texrunner.expectqueue.put_nowait(None)              # do not expect any output anymore
        if texrunner.mode == "latex":                       # try to immediately quit from TeX or LaTeX
            texrunner.texinput.write("\n\\catcode`\\@11\\relax\\@@end\n")
        else:
            texrunner.texinput.write("\n\\end\n")
        texrunner.texinput.close()                          # close the input queue and
        if not texrunner.waitforevent(texrunner.quitevent): # wait for finish of the output
            return                                          # didn't got a quit from TeX -> we can't do much more
        texrunner.texruns = 0
        texrunner.texdone = 1
    for usefile in texrunner.usefiles:
        extpos = usefile.rfind(".")
        try:
            os.rename(texrunner.texfilename + usefile[extpos:], usefile)
        except OSError:
            pass
    for file in glob.glob("%s.*" % texrunner.texfilename) + ["%sNotes.bib" % texrunner.texfilename]:
        try:
            os.unlink(file)
        except OSError:
            pass


class _unset:
    pass


class Tee(object):

    def __init__(self, *files):
        self.files = files

    def write(self, data):
        for file in self.files:
            file.write(data)

    def close(self):
        for file in self.files:
            file.close()


class texrunner:
    """TeX/LaTeX interface
    - runs TeX/LaTeX expressions instantly
    - checks TeX/LaTeX response
    - the instance variable texmessage stores the last TeX
      response as a string
    - the instance variable texmessageparsed stores a parsed
      version of texmessage; it should be empty after
      texmessage.check was called, otherwise a TexResultError
      is raised
    - the instance variable errordebug controls the verbose
      level of TexResultError"""

    defaulttexmessagesstart = [texmessage.start]
    defaulttexmessagesdocclass = [texmessage.load]
    defaulttexmessagesbegindoc = [texmessage.load, texmessage.noaux]
    defaulttexmessagesend = [texmessage.end, texmessage.fontwarning, texmessage.rerunwarning, texmessage.nobblwarning]
    defaulttexmessagesdefaultpreamble = [texmessage.load]
    defaulttexmessagesdefaultrun = [texmessage.loaddef, texmessage.graphicsload,
                                    texmessage.fontwarning, texmessage.boxwarning, texmessage.packagewarning]

    def __init__(self, mode="tex",
                       lfs="10pt",
                       docclass="article",
                       docopt=None,
                       texenc="ascii",
                       usefiles=[],
                       waitfortex=config.getint("text", "waitfortex", 60),
                       showwaitfortex=config.getint("text", "showwaitfortex", 5),
                       texipc=config.getboolean("text", "texipc", 0),
                       texdebug=None,
                       dvidebug=0,
                       errordebug=1,
                       pyxgraphics=1,
                       texmessagesstart=[],
                       texmessagesdocclass=[],
                       texmessagesbegindoc=[],
                       texmessagesend=[],
                       texmessagesdefaultpreamble=[],
                       texmessagesdefaultrun=[]):
        mode = mode.lower()
        if mode != "tex" and mode != "latex":
            raise ValueError("mode \"TeX\" or \"LaTeX\" expected")
        self.mode = mode
        self.lfs = lfs
        self.docclass = docclass
        self.docopt = docopt
        self.texenc = texenc
        self.usefiles = usefiles[:]
        self.waitfortex = waitfortex
        self.showwaitfortex = showwaitfortex
        self.texipc = texipc
        self.texdebug = texdebug
        self.dvidebug = dvidebug
        self.errordebug = errordebug
        self.pyxgraphics = pyxgraphics
        self.texmessagesstart = texmessagesstart[:]
        self.texmessagesdocclass = texmessagesdocclass[:]
        self.texmessagesbegindoc = texmessagesbegindoc[:]
        self.texmessagesend = texmessagesend[:]
        self.texmessagesdefaultpreamble = texmessagesdefaultpreamble[:]
        self.texmessagesdefaultrun = texmessagesdefaultrun[:]

        self.texruns = 0
        self.texdone = 0
        self.preamblemode = 1
        self.executeid = 0
        self.page = 0
        self.preambles = []
        self.needdvitextboxes = [] # when texipc-mode off
        self.dvifile = None
        self.textboxesincluded = 0
        savetempdir = tempfile.tempdir
        tempfile.tempdir = os.curdir
        self.texfilename = os.path.basename(tempfile.mktemp())
        tempfile.tempdir = savetempdir

    def waitforevent(self, event):
        """waits verbosely with an timeout for an event
        - observes an event while periodly while printing messages
        - returns the status of the event (isSet)
        - does not clear the event"""
        if self.showwaitfortex:
            waited = 0
            hasevent = 0
            while waited < self.waitfortex and not hasevent:
                if self.waitfortex - waited > self.showwaitfortex:
                    event.wait(self.showwaitfortex)
                    waited += self.showwaitfortex
                else:
                    event.wait(self.waitfortex - waited)
                    waited += self.waitfortex - waited
                hasevent = event.isSet()
                if not hasevent:
                    if waited < self.waitfortex:
                        warnings.warn("still waiting for %s after %i (of %i) seconds..." % (self.mode, waited, self.waitfortex), PyXTeXWarning)
                    else:
                        warnings.warn("the timeout of %i seconds expired and %s did not respond." % (waited, self.mode), PyXTeXWarning)
            return hasevent
        else:
            event.wait(self.waitfortex)
            return event.isSet()

    def execute(self, expr, texmessages):
        """executes expr within TeX/LaTeX
        - if self.texruns is not yet set, TeX/LaTeX is initialized,
          self.texruns is set and self.preamblemode is set
        - the method must not be called, when self.texdone is already set
        - expr should be a string or None
        - when expr is None, TeX/LaTeX is stopped, self.texruns is unset and
          self.texdone becomes set
        - when self.preamblemode is set, the expr is passed directly to TeX/LaTeX
        - when self.preamblemode is unset, the expr is passed to \ProcessPyXBox
        - texmessages is a list of texmessage instances"""
        if not self.texruns:
            for usefile in self.usefiles:
                extpos = usefile.rfind(".")
                try:
                    os.rename(usefile, self.texfilename + usefile[extpos:])
                except OSError:
                    pass
            texfile = open("%s.tex" % self.texfilename, "w") # start with filename -> creates dvi file with that name
            texfile.write("\\relax%\n")
            texfile.close()
            if self.texipc:
                ipcflag = " --ipc"
            else:
                ipcflag = ""
            try:
                self.texinput, self.texoutput = pycompat.popen4("%s%s %s" % (self.mode, ipcflag, self.texfilename), "t", 0)
            except ValueError:
                # workaround: bufsize = 0 is not supported on MS windows for os.open4 (Python 2.4 and below, i.e. where subprocess is not available)
                self.texinput, self.texoutput = pycompat.popen4("%s%s %s" % (self.mode, ipcflag, self.texfilename), "t")
            if self.texdebug:
                self.texinput = Tee(self.texinput, open(self.texdebug, "wb"))
            atexit.register(_cleantmp, self)
            self.expectqueue = queue.Queue(1)  # allow for a single entry only -> keeps the next InputMarker to be wait for
            self.gotevent = threading.Event()  # keeps the got inputmarker event
            self.gotqueue = queue.Queue(0)     # allow arbitrary number of entries
            self.quitevent = threading.Event() # keeps for end of terminal event
            self.readoutput = _readpipe(self.texoutput, self.expectqueue, self.gotevent, self.gotqueue, self.quitevent)
            self.texruns = 1
            oldpreamblemode = self.preamblemode
            self.preamblemode = 1
            self.readoutput.start()
            self.execute("\\scrollmode\n\\raiseerror%\n" # switch to and check scrollmode
                         "\\def\\PyX{P\\kern-.3em\\lower.5ex\hbox{Y}\kern-.18em X}%\n" # just the PyX Logo
                         "\\gdef\\PyXBoxHAlign{0}%\n" # global PyXBoxHAlign (0.0-1.0) for the horizontal alignment, default to 0
                         "\\newbox\\PyXBox%\n" # PyXBox will contain the output
                         "\\newbox\\PyXBoxHAligned%\n" # PyXBox will contain the horizontal aligned output
                         "\\newdimen\\PyXDimenHAlignLT%\n" # PyXDimenHAlignLT/RT will contain the left/right extent
                         "\\newdimen\\PyXDimenHAlignRT%\n" +
                         _textattrspreamble + # insert preambles for textattrs macros
                         "\\long\\def\\ProcessPyXBox#1#2{%\n" # the ProcessPyXBox definition (#1 is expr, #2 is page number)
                         "\\setbox\\PyXBox=\\hbox{{#1}}%\n" # push expression into PyXBox
                         "\\PyXDimenHAlignLT=\\PyXBoxHAlign\\wd\\PyXBox%\n" # calculate the left/right extent
                         "\\PyXDimenHAlignRT=\\wd\\PyXBox%\n"
                         "\\advance\\PyXDimenHAlignRT by -\\PyXDimenHAlignLT%\n"
                         "\\gdef\\PyXBoxHAlign{0}%\n" # reset the PyXBoxHAlign to the default 0
                         "\\immediate\\write16{PyXBox:page=#2," # write page and extents of this box to stdout
                                                     "lt=\\the\\PyXDimenHAlignLT,"
                                                     "rt=\\the\\PyXDimenHAlignRT,"
                                                     "ht=\\the\\ht\\PyXBox,"
                                                     "dp=\\the\\dp\\PyXBox:}%\n"
                         "\\setbox\\PyXBoxHAligned=\\hbox{\\kern-\\PyXDimenHAlignLT\\box\\PyXBox}%\n" # align horizontally
                         "\\ht\\PyXBoxHAligned0pt%\n" # baseline alignment (hight to zero)
                         "{\\count0=80\\count1=121\\count2=88\\count3=#2\\shipout\\box\\PyXBoxHAligned}}%\n" # shipout PyXBox to Page 80.121.88.<page number>
                         "\\def\\PyXInput#1{\\immediate\\write16{PyXInputMarker:executeid=#1:}}%\n" # write PyXInputMarker to stdout
                         "\\def\\PyXMarker#1{\\hskip0pt\\special{PyX:marker #1}}%", # write PyXMarker special into the dvi-file
                         self.defaulttexmessagesstart + self.texmessagesstart)
            os.remove("%s.tex" % self.texfilename)
            if self.mode == "tex":
                if self.lfs:
                    if not self.lfs.endswith(".lfs"):
                        self.lfs = "%s.lfs" % self.lfs
                    lfsfile = config.open(self.lfs, [], "r")
                    lfsdef = lfsfile.read().decode("ascii")
                    lfsfile.close()
                    self.execute(lfsdef, [])
                    self.execute("\\normalsize%\n", [])
                self.execute("\\newdimen\\linewidth\\newdimen\\textwidth%\n", [])
            elif self.mode == "latex":
                if self.pyxgraphics:
                    pyxdef = config.open("pyx.def", [], "rb")
                    pyxdef_filename = self.texfilename + ".pyx.def"
                    pyxdef_file = open(pyxdef_filename, "wb")
                    pyxdef_file.write(pyxdef.read())
                    pyxdef.close()
                    pyxdef_file.close()
                    pyxdef_filename_tex = os.path.abspath(pyxdef_filename).replace(os.sep, "/")
                    self.execute("\\makeatletter%\n"
                                 "\\let\\saveProcessOptions=\\ProcessOptions%\n"
                                 "\\def\\ProcessOptions{%\n"
                                 "\\def\\Gin@driver{" + pyxdef_filename_tex + "}%\n"
                                 "\\def\\c@lor@namefile{dvipsnam.def}%\n"
                                 "\\saveProcessOptions}%\n"
                                 "\\makeatother",
                                 [])
                if self.docopt is not None:
                    self.execute("\\documentclass[%s]{%s}" % (self.docopt, self.docclass),
                                 self.defaulttexmessagesdocclass + self.texmessagesdocclass)
                else:
                    self.execute("\\documentclass{%s}" % self.docclass,
                                 self.defaulttexmessagesdocclass + self.texmessagesdocclass)
            self.preamblemode = oldpreamblemode
        self.executeid += 1
        if expr is not None: # TeX/LaTeX should process expr
            self.expectqueue.put_nowait(("PyXInputMarker:executeid=%i:" % self.executeid).encode(self.texenc))
            if self.preamblemode:
                self.expr = ("%s%%\n" % expr +
                             "\\PyXInput{%i}%%\n" % self.executeid)
            else:
                self.page += 1
                self.expr = ("\\ProcessPyXBox{%s%%\n}{%i}%%\n" % (expr, self.page) +
                             "\\PyXInput{%i}%%\n" % self.executeid)
        else: # TeX/LaTeX should be finished
            self.expectqueue.put_nowait(("Transcript written on %s.log" % self.texfilename).encode(self.texenc))
            if self.mode == "latex":
                self.expr = "\\end{document}%\n"
            else:
                self.expr = "\\end%\n"
        self.texinput.write(self.expr.encode(self.texenc))
        gotevent = self.waitforevent(self.gotevent)
        self.gotevent.clear()
        if expr is None and gotevent: # TeX/LaTeX should have finished
            self.texruns = 0
            self.texdone = 1
            self.texinput.close()                        # close the input queue and
            gotevent = self.waitforevent(self.quitevent) # wait for finish of the output
        try:
            self.texmessage = ""
            while 1:
                self.texmessage += self.gotqueue.get_nowait().decode(self.texenc)
        except queue.Empty:
            pass
        self.texmessage = self.texmessage.replace("\r\n", "\n").replace("\r", "\n")
        self.texmessageparsed = self.texmessage
        if gotevent:
            if expr is not None:
                texmessage.inputmarker.check(self)
                if not self.preamblemode:
                    texmessage.pyxbox.check(self)
                    texmessage.pyxpageout.check(self)
            texmessages = attr.mergeattrs(texmessages)
            for t in texmessages:
                t.check(self)
            keeptexmessageparsed = self.texmessageparsed
            texmessage.emptylines.check(self)
            if len(self.texmessageparsed):
                self.texmessageparsed = keeptexmessageparsed
                raise TexResultError("unhandled TeX response (might be an error)", self)
        else:
            raise TexResultError("TeX didn't respond as expected within the timeout period (%i seconds)." % self.waitfortex, self)

    def finishdvi(self, ignoretail=0):
        """finish TeX/LaTeX and read the dvifile
        - this method ensures that all textboxes can access their
          dvicanvas"""
        self.execute(None, self.defaulttexmessagesend + self.texmessagesend)
        dvifilename = "%s.dvi" % self.texfilename
        if not self.texipc:
            self.dvifile = dvifile.DVIfile(dvifilename, debug=self.dvidebug)
            page = 1
            for box in self.needdvitextboxes:
                box.setdvicanvas(self.dvifile.readpage([ord("P"), ord("y"), ord("X"), page, 0, 0, 0, 0, 0, 0], fontmap=box.fontmap, singlecharmode=box.singlecharmode))
                page += 1
        if not ignoretail and self.dvifile.readpage(None) is not None:
            raise RuntimeError("end of dvifile expected")
        self.dvifile = None
        self.needdvitextboxes = []

    def reset(self, reinit=0):
        "resets the tex runner to its initial state (upto its record to old dvi file(s))"
        if self.texruns:
            self.finishdvi()
        self.executeid = 0
        self.page = 0
        self.texdone = 0
        if reinit:
            self.preamblemode = 1
            for expr, texmessages in self.preambles:
                self.execute(expr, texmessages)
            if self.mode == "latex":
                self.execute("\\begin{document}", self.defaulttexmessagesbegindoc + self.texmessagesbegindoc)
            self.preamblemode = 0
        else:
            self.preambles = []
            self.preamblemode = 1

    def set(self, mode=_unset,
                  lfs=_unset,
                  docclass=_unset,
                  docopt=_unset,
                  texenc=_unset,
                  usefiles=_unset,
                  waitfortex=_unset,
                  showwaitfortex=_unset,
                  texipc=_unset,
                  texdebug=_unset,
                  dvidebug=_unset,
                  errordebug=_unset,
                  pyxgraphics=_unset,
                  texmessagesstart=_unset,
                  texmessagesdocclass=_unset,
                  texmessagesbegindoc=_unset,
                  texmessagesend=_unset,
                  texmessagesdefaultpreamble=_unset,
                  texmessagesdefaultrun=_unset):
        """provide a set command for TeX/LaTeX settings
        - TeX/LaTeX must not yet been started
        - especially needed for the defaultrunner, where no access to
          the constructor is available"""
        if self.texruns:
            raise RuntimeError("set not allowed -- TeX/LaTeX already started")
        if mode is not _unset:
            mode = mode.lower()
            if mode != "tex" and mode != "latex":
                raise ValueError("mode \"TeX\" or \"LaTeX\" expected")
            self.mode = mode
        if lfs is not _unset:
            self.lfs = lfs
        if docclass is not _unset:
            self.docclass = docclass
        if docopt is not _unset:
            self.docopt = docopt
        if texenc is not _unset:
            self.texenc = texenc
        if usefiles is not _unset:
            self.usefiles = usefiles
        if waitfortex is not _unset:
            self.waitfortex = waitfortex
        if showwaitfortex is not _unset:
            self.showwaitfortex = showwaitfortex
        if texipc is not _unset:
            self.texipc = texipc
        if texdebug is not _unset:
            self.texdebug = texdebug
        if dvidebug is not _unset:
            self.dvidebug = dvidebug
        if errordebug is not _unset:
            self.errordebug = errordebug
        if pyxgraphics is not _unset:
            self.pyxgraphics = pyxgraphics
        if errordebug is not _unset:
            self.errordebug = errordebug
        if texmessagesstart is not _unset:
            self.texmessagesstart = texmessagesstart
        if texmessagesdocclass is not _unset:
            self.texmessagesdocclass = texmessagesdocclass
        if texmessagesbegindoc is not _unset:
            self.texmessagesbegindoc = texmessagesbegindoc
        if texmessagesend is not _unset:
            self.texmessagesend = texmessagesend
        if texmessagesdefaultpreamble is not _unset:
            self.texmessagesdefaultpreamble = texmessagesdefaultpreamble
        if texmessagesdefaultrun is not _unset:
            self.texmessagesdefaultrun = texmessagesdefaultrun

    def preamble(self, expr, texmessages=[]):
        r"""put something into the TeX/LaTeX preamble
        - in LaTeX, this is done before the \begin{document}
          (you might use \AtBeginDocument, when you're in need for)
        - it is not allowed to call preamble after calling the
          text method for the first time (for LaTeX this is needed
          due to \begin{document}; in TeX it is forced for compatibility
          (you should be able to switch from TeX to LaTeX, if you want,
          without breaking something)
        - preamble expressions must not create any dvi output
        - args might contain texmessage instances"""
        if self.texdone or not self.preamblemode:
            raise RuntimeError("preamble calls disabled due to previous text calls")
        texmessages = self.defaulttexmessagesdefaultpreamble + self.texmessagesdefaultpreamble + texmessages
        self.execute(expr, texmessages)
        self.preambles.append((expr, texmessages))

    PyXBoxPattern = re.compile(r"PyXBox:page=(?P<page>\d+),lt=(?P<lt>-?\d*((\d\.?)|(\.?\d))\d*)pt,rt=(?P<rt>-?\d*((\d\.?)|(\.?\d))\d*)pt,ht=(?P<ht>-?\d*((\d\.?)|(\.?\d))\d*)pt,dp=(?P<dp>-?\d*((\d\.?)|(\.?\d))\d*)pt:")

    def text(self, x, y, expr, textattrs=[], texmessages=[], fontmap=None, singlecharmode=False):
        """create text by passing expr to TeX/LaTeX
        - returns a textbox containing the result from running expr thru TeX/LaTeX
        - the box center is set to x, y
        - *args may contain attr parameters, namely:
          - textattr instances
          - texmessage instances
          - trafo._trafo instances
          - style.fillstyle instances"""
        if expr is None:
            raise ValueError("None expression is invalid")
        if self.texdone:
            self.reset(reinit=1)
        first = 0
        if self.preamblemode:
            if self.mode == "latex":
                self.execute("\\begin{document}", self.defaulttexmessagesbegindoc + self.texmessagesbegindoc)
            self.preamblemode = 0
            first = 1
        textattrs = attr.mergeattrs(textattrs) # perform cleans
        attr.checkattrs(textattrs, [textattr, trafo.trafo_pt, style.fillstyle])
        trafos = attr.getattrs(textattrs, [trafo.trafo_pt])
        fillstyles = attr.getattrs(textattrs, [style.fillstyle])
        textattrs = attr.getattrs(textattrs, [textattr])
        # reverse loop over the merged textattrs (last is applied first)
        lentextattrs = len(textattrs)
        for i in range(lentextattrs):
            expr = textattrs[lentextattrs-1-i].apply(expr)
        try:
            self.execute(expr, self.defaulttexmessagesdefaultrun + self.texmessagesdefaultrun + texmessages)
        except TexResultError as e:
            warnings.warn("We try to finish the dvi due to an unhandled tex error", PyXTeXWarning)
            try:
                self.finishdvi(ignoretail=1)
            except TexResultError:
                pass
            raise e
        if self.texipc:
            if first:
                self.dvifile = dvifile.DVIfile("%s.dvi" % self.texfilename, debug=self.dvidebug)
        match = self.PyXBoxPattern.search(self.texmessage)
        if not match or int(match.group("page")) != self.page:
            raise TexResultError("box extents not found", self)
        left, right, height, depth = [float(xxx)*72/72.27*unit.x_pt for xxx in match.group("lt", "rt", "ht", "dp")]
        box = textbox(x, y, left, right, height, depth, self.finishdvi, fillstyles)
        for t in trafos:
            box.reltransform(t) # TODO: should trafos really use reltransform???
                                #       this is quite different from what we do elsewhere!!!
                                #       see https://sourceforge.net/mailarchive/forum.php?thread_id=9137692&forum_id=23700
        if self.texipc:
            box.setdvicanvas(self.dvifile.readpage([ord("P"), ord("y"), ord("X"), self.page, 0, 0, 0, 0, 0, 0], fontmap=fontmap, singlecharmode=singlecharmode))
        else:
            box.fontmap = fontmap
            box.singlecharmode = singlecharmode
            self.needdvitextboxes.append(box)
        return box

    def text_pt(self, x, y, expr, *args, **kwargs):
        return self.text(x * unit.t_pt, y * unit.t_pt, expr, *args, **kwargs)

    PyXVariableBoxPattern = re.compile(r"PyXVariableBox:page=(?P<page>\d+),par=(?P<par>\d+),prevgraf=(?P<prevgraf>\d+):")

    def textboxes(self, text, pageshapes):
        # this is some experimental code to put text into several boxes
        # while the bounding shape changes from box to box (rectangles only)
        # first we load sev.tex
        if not self.textboxesincluded:
            self.execute(r"\input textboxes.tex", [texmessage.load])
            self.textboxesincluded = 1
        # define page shapes
        pageshapes_str = "\\hsize=%.5ftruept%%\n\\vsize=%.5ftruept%%\n" % (72.27/72*unit.topt(pageshapes[0][0]), 72.27/72*unit.topt(pageshapes[0][1]))
        pageshapes_str += "\\lohsizes={%\n"
        for hsize, vsize in pageshapes[1:]:
            pageshapes_str += "{\\global\\hsize=%.5ftruept}%%\n" % (72.27/72*unit.topt(hsize))
        pageshapes_str += "{\\relax}%\n}%\n"
        pageshapes_str += "\\lovsizes={%\n"
        for hsize, vsize in pageshapes[1:]:
            pageshapes_str += "{\\global\\vsize=%.5ftruept}%%\n" % (72.27/72*unit.topt(vsize))
        pageshapes_str += "{\\relax}%\n}%\n"
        page = 0
        parnos = []
        parshapes = []
        loop = 0
        while 1:
            self.execute(pageshapes_str, [])
            parnos_str = "}{".join(parnos)
            if parnos_str:
                parnos_str = "{%s}" % parnos_str
            parnos_str = "\\parnos={%s{\\relax}}%%\n" % parnos_str
            self.execute(parnos_str, [])
            parshapes_str = "\\parshapes={%%\n%s%%\n{\\relax}%%\n}%%\n" % "%\n".join(parshapes)
            self.execute(parshapes_str, [])
            self.execute("\\global\\count0=1%%\n"
                         "\\global\\parno=0%%\n"
                         "\\global\\myprevgraf=0%%\n"
                         "\\global\\showprevgraf=0%%\n"
                         "\\global\\outputtype=0%%\n"
                         "\\global\\leastcost=10000000%%\n"
                         "%s%%\n"
                         "\\vfill\\supereject%%\n" % text, [texmessage.ignore])
            if self.texipc:
                if self.dvifile is None:
                    self.dvifile = dvifile.DVIfile("%s.dvi" % self.texfilename, debug=self.dvidebug)
            else:
                raise RuntimeError("textboxes currently needs texipc")
            lastparnos = parnos
            parnos = []
            lastparshapes = parshapes
            parshapes = []
            pages = 0
            lastpar = prevgraf = -1
            m = self.PyXVariableBoxPattern.search(self.texmessage)
            while m:
                pages += 1
                page = int(m.group("page"))
                assert page == pages
                par = int(m.group("par"))
                prevgraf = int(m.group("prevgraf"))
                if page <= len(pageshapes):
                    width = 72.27/72*unit.topt(pageshapes[page-1][0])
                else:
                    width = 72.27/72*unit.topt(pageshapes[-1][0])
                if page < len(pageshapes):
                    nextwidth = 72.27/72*unit.topt(pageshapes[page][0])
                else:
                    nextwidth = 72.27/72*unit.topt(pageshapes[-1][0])

                if par != lastpar:
                    # a new paragraph is to be broken
                    parnos.append(str(par))
                    parshape = " 0pt ".join(["%.5ftruept" % width for i in range(prevgraf)])
                    if len(parshape):
                        parshape = " 0pt " + parshape
                    parshapes.append("{\\parshape %i%s 0pt %.5ftruept}" % (prevgraf + 1, parshape, nextwidth))
                elif prevgraf == lastprevgraf:
                    pass
                else:
                    # we have to append the breaking of the previous paragraph
                    oldparshape = " ".join(parshapes[-1].split(" ")[2:2+2*lastprevgraf])
                    oldparshape = oldparshape.split("}")[0]
                    if len(parshape):
                        oldparshape = " " + oldparshape
                    parshape = " 0pt ".join(["%.5ftruept" % width for i in range(prevgraf - lastprevgraf)])
                    if len(parshape):
                        parshape = " 0pt " + parshape
                    else:
                        parshape = " "
                    parshapes[-1] = "{\\parshape %i%s%s 0pt %.5ftruept}" % (prevgraf + 1, oldparshape, parshape, nextwidth)
                lastpar = par
                lastprevgraf = prevgraf
                nextpos = m.end()
                m = self.PyXVariableBoxPattern.search(self.texmessage, nextpos)
            result = []
            for i in range(pages):
                result.append(self.dvifile.readpage([i + 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
            if parnos == lastparnos and parshapes == lastparshapes:
                return result
            loop += 1
            if loop > 100:
                raise TexResultError("Too many loops in textboxes ", texrunner)


# the module provides an default texrunner and methods for direct access
defaulttexrunner = texrunner()
reset = defaulttexrunner.reset
set = defaulttexrunner.set
preamble = defaulttexrunner.preamble
text = defaulttexrunner.text
text_pt = defaulttexrunner.text_pt

def escapestring(s, replace={" ": "~",
                             "$": "\\$",
                             "&": "\\&",
                             "#": "\\#",
                             "_": "\\_",
                             "%": "\\%",
                             "^": "\\string^",
                             "~": "\\string~",
                             "<": "{$<$}",
                             ">": "{$>$}",
                             "{": "{$\{$}",
                             "}": "{$\}$}",
                             "\\": "{$\setminus$}",
                             "|": "{$\mid$}"}):
    "escape all ascii characters such that they are printable by TeX/LaTeX"
    i = 0
    while i < len(s):
        if not 32 <= ord(s[i]) < 127:
            raise ValueError("escapestring function handles ascii strings only")
        c = s[i]
        try:
            r = replace[c]
        except KeyError:
            i += 1
        else:
            s = s[:i] + r + s[i+1:]
            i += len(r)
    return s
