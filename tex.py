#!/usr/bin/env python
#
#
# Copyright (C) 2002 J�rg Lehmann <joergl@users.sourceforge.net>
# Copyright (C) 2002 Andr� Wobst <wobsta@users.sourceforge.net>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""
(La)TeX interface of PyX

This module provides the classes tex and latex, which can be inserted into a
PyX canvas. The method (la)tex.text are used to print out text, while
(la)tex.textwd, tex.textht, and tex.textdp appraise the width, height, and
depth of a text, respectively.
"""

import os, string, tempfile, sys, md5, traceback, time, StringIO, re
import base, unit, epsfile, color, instancelist


################################################################################
# TeX attributes
################################################################################

class _texattr:

    """base class for all TeX attributes"""

    pass


class fontsize(_texattr):
    
    """fontsize TeX attribute"""
    
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value


fontsize.tiny = fontsize("tiny")
fontsize.scriptsize = fontsize("scriptsize")
fontsize.footnotesize = fontsize("footnotesize")
fontsize.small = fontsize("small")
fontsize.normalsize = fontsize("normalsize")
fontsize.large = fontsize("large")
fontsize.Large = fontsize("Large")
fontsize.LARGE = fontsize("LARGE")
fontsize.huge = fontsize("huge")
fontsize.Huge = fontsize("Huge")


class halign(_texattr):
    
    """tex horizontal align attribute"""

    def __init__(self, value):
        self.value = value

    def __cmp__(self, other):
        return cmp(self.value, other.value)

    __rcmp__ = __cmp__


halign.left   = halign("left")
halign.center = halign("center")
halign.right  = halign("right")

   
class valign(_texattr):

    """abstract tex vertical align attribute"""

    def __init__(self, hsize):
        self.hsize = hsize


class _valignvtop(valign):

    """tex top vertical align attribute"""

    pass


valign.top = _valignvtop


class _valignvbox(valign):

    """tex bottom vertical align attribute"""

    pass


valign.bottom = _valignvbox


class direction(_texattr):

    """tex output direction attribute"""

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return "%.5f" % self.value



direction.horizontal = direction(0)
direction.vertical   = direction(90)
direction.upsidedown = direction(180)
direction.rvertical  = direction(270)


class style(_texattr):

    """tex style modification attribute"""

    def __init__(self, praefix, suffix):
        self.praefix = praefix
        self.suffix = suffix

    def ModifyCmd(self, cmd):
        return self.praefix + cmd + self.suffix


style.text = style("", "")
style.math = style("$\displaystyle{}", "$")


#
# TeX message handlers
#

class msghandler(_texattr):

    """abstract base class for tex message handlers
    
    A message handler has to provide a parsemsg method. It gets a string and
    returns a string. Within the parsemsg method the handler may remove any
    part of the message it is familiar with."""

    def removeemptylines(self, msg):
        """any message parser may use this method to remove empty lines"""

        msg = re.sub("^(" + os.linesep + ")*", "", msg)
        msg = re.sub("(" + os.linesep + "){3,}", os.linesep + os.linesep, msg)
        msg = re.sub("(" + os.linesep + ")+$", os.linesep, msg)
        return msg


class _msghandlercombine(msghandler):

    """a message handler, which combines different message handlers"""

    def __init__(self, *handlerlst):
        self.handlerlst = handlerlst
    
    def parsemsg(self, msg):
        for handler in self.handlerlst:
            msg = handler.parsemsg(msg)
        return msg


msghandler.combine = _msghandlercombine


class _msghandlershowall(msghandler):

    """a message handler, which shows all messages"""

    def parsemsg(self, msg):
        return msg


msghandler.showall = _msghandlershowall()

class _msghandlerhideload(msghandler):

    """a message handler, which hides all messages inside proper '(filename' and ')'
    the string filename has to be a readable file"""

    def parsemsg(self, msg):
        depth = 0
        newstr = ""
        newlevel = 0
        for c in msg:
            if newlevel and (c in (list(string.whitespace) + ["(", ")"])):
                if not len(filestr):
                    break
                if not os.access(filestr,os.R_OK):
                    break
                newlevel = 0
            if c == "(":
                depth += 1
                filestr = ""
                newlevel = 1
            elif c == ")":
                depth -= 1
                if depth < 0:
                    break
            elif depth == 0:
                newstr += c
            else:
                filestr += c
        else:
            # replace msg only if loop was completed and no ")" is missing
            if depth == 0:
                msg = self.removeemptylines(newstr)
        return msg


msghandler.hideload = _msghandlerhideload()


class _msghandlerhidegraphicsload(msghandler):

    """a message handler, which hides all messages inside like '<filename>'
    the string filename has to be a readable file"""

    def parsemsg(self, msg):
        depth = 0
        newstr = ""
        for c in msg:
            if c == "<":
                depth += 1
                if depth > 1:
                    break
                filestr = ""
            elif c == ">":
                depth -= 1
                if depth < 0:
                    break
                if not os.access(filestr,os.R_OK):
                    newstr += "<" + filestr + ">"
            elif depth == 0:
                newstr += c
            else:
                filestr += c
        else:
            # replace msg only if loop was completed and no ">" missing
            if depth == 0:
                msg = self.removeemptylines(newstr)
        return msg


msghandler.hidegraphicsload = _msghandlerhidegraphicsload()


class _msghandlerhidefontwarning(msghandler):

    """a message handler, which hides LaTeX font warnings, e.g.
    Messages starting with 'LaTeX Font Warning: ' which might be
    continued on following lines by '(Font)              '"""

    def parsemsg(self, msg):
        msglines = string.split(msg, os.linesep)
        newmsglines = []
        fontwarning = 0
        for line in msglines:
            if fontwarning and line[:20] != "(Font)              ":
                fontwarning = 0
            if not fontwarning and line[:20] == "LaTeX Font Warning: ":
                fontwarning = 1
            if not fontwarning:
                newmsglines.append(line)
        newmsg = reduce(lambda x, y: x + y + os.linesep, newmsglines, "")
        return self.removeemptylines(newmsg)


msghandler.hidefontwarning = _msghandlerhidefontwarning()


class _msghandlerhidebuterror(msghandler):

    """a message handler, hides all messages whenever they do
    not contain a line starting with '! '"""

    def parsemsg(self, msg):
        # the os.linesep + msg instead of msg itself is needed, if the message starts with "! "
        if string.find(os.linesep + msg, os.linesep + "! ") != -1:
            return msg
        else:
            return ""


msghandler.hidebuterror = _msghandlerhidebuterror()


class _msghandlerhideall(msghandler):

    """a message handler, which hides all messages"""

    def parsemsg(self, msg):
        return ""


msghandler.hideall = _msghandlerhideall()


################################################################################
# TeX exceptions
################################################################################

class TexExcept(base.PyXExcept):

    pass


class TexLeftParenthesisError(TexExcept):

    def __str__(self):
        return "no matching parenthesis for '{' found"


class TexRightParenthesisError(TexExcept):

    def __str__(self):
        return "no matching parenthesis for '}' found"


class TexHalignError(TexExcept):

    def __str__(self):
        return "unkown halign"


class TexValignError(TexExcept):

    def __str__(self):
        return "unkown valign"


class TexDefAfterBoxError(TexExcept):

    def __str__(self):
        return "definition commands not allowed after output commands"


################################################################################
# modules internal stuff
################################################################################

class _extent:

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value


_extent.wd = _extent("wd")
_extent.ht = _extent("ht")
_extent.dp = _extent("dp")
   

class _TexCmd:

    """class for all user supplied commands"""

    PyxMarker = "PyxMarker"
    BeginPyxMarker = "Begin" + PyxMarker
    EndPyxMarker = "End" + PyxMarker

    def __init__(self, Marker, Stack, msghandler):
        self.Marker = Marker
        self.Stack = Stack
        self.msghandler = msghandler

    def TexParenthesisCheck(self, Cmd):
        """check for proper usage of "{" and "}" in Cmd"""

        depth = 0
        esc = 0
        for c in Cmd:
            if c == "{" and not esc:
                depth = depth + 1
            if c == "}" and not esc:
                depth = depth - 1
                if depth < 0:
                    raise TexRightParenthesisError
            if c == "\\":
                esc = (esc + 1) % 2
            else:
                esc = 0
        if depth > 0:
            raise TexLeftParenthesisError

    def BeginMarkerStr(self):
        return "%s[%s]" % (self.BeginPyxMarker, self.Marker, )
    
    def WriteBeginMarker(self, file):
        file.write("\\immediate\\write16{%s}%%\n" % self.BeginMarkerStr())

    def EndMarkerStr(self):
        return "%s[%s]" % (self.EndPyxMarker, self.Marker, )

    def WriteEndMarker(self, file):
        file.write("\\immediate\\write16{%s}%%\n" % self.EndMarkerStr())

    def CheckMarkerError(self, file):
        """read markers and identify the message"""

        line = file.readline()
        while line[:-1] != self.BeginMarkerStr():
            line = file.readline()
        msg = ""
        line = file.readline()
        while (line != "") and (line[:-1] != self.EndMarkerStr()):
            msg = msg + line
            line = file.readline()
        if line == "":
            print "Traceback (innermost last):"
            traceback.print_list(self.Stack)
            print "(La)TeX Message:"
            print msg
            raise IOError
        else:
            # check if message can be ignored
            doprint = 0
            parsedmsg = self.msghandler.parsemsg(msg)
            for c in parsedmsg:
                if c not in string.whitespace:
                    print "Traceback (innermost last):"
                    traceback.print_list(self.Stack)
                    print "(La)TeX Message:"
                    print parsedmsg
                    break


class _DefCmd(_TexCmd):

    """definition commands"""

    def __init__(self, DefCmd, Marker, Stack, msghandler):
        _TexCmd.__init__(self, Marker, Stack, msghandler)
        self.TexParenthesisCheck(DefCmd)
        self.DefCmd = DefCmd

    def write(self, file):
        self.WriteBeginMarker(file)
        file.write(self.DefCmd)
        self.WriteEndMarker(file)


class _CmdPut:

    """print parameters for a BoxCmd"""

    def __init__(self, x, y, halign, direction, color):
        self.x = x
        self.y = y
        self.halign = halign
        self.direction = direction
        self.color = color


class _BoxCmd(_TexCmd):

    """BoxCmd (for printing text and getting extents)"""

    def __init__(self, DefCmdsStr, BoxCmd, style, fontsize, valign, Marker, Stack, msghandler):
        _TexCmd.__init__(self, Marker, Stack, msghandler)
        self.TexParenthesisCheck(BoxCmd)
        self.DefCmdsStr = DefCmdsStr
        self.BoxCmd = "{%s}" % BoxCmd # add another "{" to ensure, that everything goes into the Box
        self.CmdPuts = [] # list, where to put the command
        self.CmdExtents = [] # list, which extents are requested

        self.BoxCmd = style.ModifyCmd(self.BoxCmd)
        if valign is not None:
            if isinstance(valign, _valignvtop):
                self.BoxCmd = "\\linewidth%.5ftruept\\vtop{\\hsize\\linewidth{%s}}" % \
                               (unit.topt(valign.hsize) * 72.27/72, self.BoxCmd, )
            elif isinstance(valign, _valignvbox):
                self.BoxCmd = "\\linewidth%.5ftruept\\vbox{\\hsize\\linewidth{%s}}" % \
                               (unit.topt(valign.hsize) * 72.27/72, self.BoxCmd, )
            else:
                raise TexValignError
        self.BoxCmd = "\\setbox\\localbox=\\hbox{\\%s%s}%%\n" % (fontsize, self.BoxCmd, )

    def __cmp__(self, other):
        return cmp(self.BoxCmd, other.BoxCmd)

    __rcmp__ = __cmp__

    def write(self, file):
        self.WriteBeginMarker(file)
        file.write(self.BoxCmd)
        self.WriteEndMarker(file)
        for CmdExtent in self.CmdExtents:
            file.write("\\immediate\\write\\sizefile{%s:%s:%s:\\the\\%s\\localbox}%%\n" %
                       (self.MD5(), CmdExtent, time.time(), CmdExtent, ))
        for CmdPut in self.CmdPuts:

            file.write("{\\vbox to0pt{\\kern%struept\\hbox{\\kern%struept\\ht\\localbox0pt" %
                        (-CmdPut.y, CmdPut.x))

            if CmdPut.direction != direction.horizontal:
                file.write("\\special{ps: gsave currentpoint currentpoint translate " +
                           str(CmdPut.direction) + " neg rotate neg exch neg exch translate }")
            if CmdPut.color != color.grey.black:
                file.write("\\special{ps: ")
                CmdPut.color.write(file)
                file.write(" }")
            if CmdPut.halign == halign.left:
                pass
            elif CmdPut.halign == halign.center:
                file.write("\kern-.5\wd\localbox")
            elif CmdPut.halign == halign.right:
                file.write("\kern-\wd\localbox")
            else:
                raise TexHalignError
            file.write("\\copy\\localbox")

            if CmdPut.color != color.grey.black:
                file.write("\\special{ps: ")
                color.grey.black.write(file)
                file.write(" }")
            if CmdPut.direction != direction.horizontal:
                file.write("\\special{ps: currentpoint grestore moveto }")
            file.write("}\\vss}\\nointerlineskip}%\n")

    def MD5(self):
        """creates an MD5 hex string for texinit + Cmd"""
    
        h = string.hexdigits
        r = ''
        s = md5.md5(self.DefCmdsStr + self.BoxCmd).digest()
        for c in s:
            i = ord(c)
            r = r + h[(i >> 4) & 0xF] + h[i & 0xF]
        return r

    def Put(self, x, y, halign, direction, color):
        self.CmdPuts.append(_CmdPut(x, y, halign, direction, color))

    def Extent(self, extent, Sizes):
        """get sizes from previous LaTeX run"""

        if extent not in self.CmdExtents:
            self.CmdExtents.append(extent)

        Str = self.MD5() + ":" + str(extent)
        for Size in Sizes:
            if Size[:len(Str)] == Str:
                texpt = float(string.rstrip(Size.split(":")[3][:-3]))
                return unit.t_pt(texpt * 72.0 / 72.27)
        return unit.t_pt(0)


################################################################################
# tex, latex class
################################################################################

class _tex(base.PSCmd, instancelist.InstanceList):

    """major parts are of tex and latex class are shared and implemented here"""

    def __init__(self, defaultmsghandler = msghandler.hideload, texfilename=None):
        self.defaultmsghandler = defaultmsghandler
        self.texfilename = texfilename
        self.DefCmds = []
        self.DefCmdsStr = None
        self.BoxCmds = []
        self.DoneRunTex = 0

        if len(os.path.basename(sys.argv[0])):
            basename = os.path.basename(sys.argv[0])
            if basename[-3:] == ".py":
                basename = basename[:-3]
            self.SizeFileName = os.path.join(os.getcwd(), basename + ".size")
        else:
            self.SizeFileName = os.path.join(os.getcwd(), "pyxput.size")
        try:
            file = open(self.SizeFileName, "r")
            self.Sizes = file.readlines()
            file.close()
        except IOError:
            self.Sizes = [ ]

    def _getstack(self):
        return traceback.extract_stack(sys._getframe())
    
    def _execute(self, command):
        if os.system(command):
            print "The exit code of the following command was non-zero:"
            print command
            print "Usually, additional information causing this trouble appears closeby."
            print "However, you may check the origin by keeping all temporary files."
            print "In order to achieve this, you have to specify a texfilename in the"
            print "constructor of the class pyx.tex. You can then try to run the command"
            print "by yourself."

    def _createaddfiles(self, tempname):
        pass

    def _removeaddfiles(self, tempname):
        pass

    def _executetex(self, tempname):
        pass

    def _executedvips(self, tempname):
        self._execute("dvips -O0in,11in -E -o %(t)s.eps %(t)s.dvi > %(t)s.dvipsout 2> %(t)s.dvipserr" % {"t": tempname})

    def _run(self):
        """run LaTeX&dvips for TexCmds, report errors, return postscript string"""
    
        if self.DoneRunTex:
            return

        if self.texfilename:
            mktemp = str(self.texfilename)
        else:
            storetempdir = tempfile.tempdir
            tempfile.tempdir = "."
            mktemp = tempfile.mktemp()
            tempfile.tempdir = storetempdir
        tempname = os.path.basename(mktemp)

        self._createaddfiles(tempname)

        texfile = open(tempname + ".tex", "w")

        texfile.write("\\nonstopmode%\n")
        texfile.write("\\def\PyX{P\\kern-.25em\\lower.5ex\\hbox{Y}\\kern-.2em X}%\n")
        texfile.write("\\newwrite\\sizefile%\n\\newbox\\localbox%\n\\newbox\\pagebox%\n")
        texfile.write("\\immediate\\openout\\sizefile=%s.size%%\n" % tempname)

        for Cmd in self.DefCmds:
            Cmd.write(texfile)

        texfile.write("\\setbox\\pagebox=\\vbox{%\n")

        for Cmd in self.BoxCmds:
            Cmd.write(texfile)

        texfile.write("}\n\\immediate\\closeout\\sizefile\n\\shipout\\copy\\pagebox\n")
        texfile.write(self._endcmd())
        texfile.close()

        self._executetex(tempname)

        try:
            outfile = open(tempname + ".texout", "r")
            for Cmd in self.DefCmds + self.BoxCmds:
                Cmd.CheckMarkerError(outfile)
            outfile.close()
        except IOError:
            print "An unexpected error occured while reading the (La)TeX output."
            print "May be, you just have no disk space available. Or something badly"
            print "in your commands caused (La)TeX to give up completely. Or your"
            print "(La)TeX installation might be broken at all."
            print "You may try to check the origin by keeping all temporary files."
            print "In order to achieve this, you have to specify a texfilename in the"
            print "constructor of the class pyx.tex. You can then try to run (La)TeX"
            print "by yourself."

        if not os.access(tempname + ".dvi", 0):
            print "Can't find the dvi file which should be produced by (La)TeX."
            print "May be, you just have no disk space available. Or something badly"
            print "in your commands caused (La)TeX to give up completely. Or your"
            print "(La)TeX installation might be broken at all."
            print "You may try to check the origin by keeping all temporary files."
            print "In order to achieve this, you have to specify a texfilename in the"
            print "constructor of the class pyx.tex. You can then try to run (La)TeX"
            print "by yourself."

        else:
            self._executedvips(tempname)
            if not os.access(tempname + ".eps", 0):
                print "Error reading the eps file which should be produced by dvips."
                print "May be, you just have no disk space available. Or something badly"
                print "in your commands caused dvips to give up completely. Or your"
                print "(La)TeX installation might be broken at all."
                print "You may try to check the origin by keeping all temporary files."
                print "In order to achieve this, you have to specify a texfilename in the"
                print "constructor of the class pyx.tex. You can then try to run dvips"
                print "by yourself."
            else:
                aepsfile = epsfile.epsfile(tempname + ".eps", translatebb=0, clip=0)
                self.bbox = aepsfile.bbox()
                epsdatafile = StringIO.StringIO()
                aepsfile.write(epsdatafile)
                self.epsdata = epsdatafile.getvalue()

        # merge new sizes
        
        OldSizes = self.Sizes

        try:
            NewSizeFile = open(tempname + ".size", "r")
            NewSizes = NewSizeFile.readlines()
        except IOError:
            NewSizes = []

        if (len(NewSizes) != 0) or (len(OldSizes) != 0):
            SizeFile = open(self.SizeFileName, "w")
            SizeFile.writelines(NewSizes)

            for OldSize in OldSizes:
                OldSizeSplit = OldSize.split(":")
                for NewSize in NewSizes:
                    if NewSize.split(":")[0:2] == OldSizeSplit[0:2]:
                        break
                else:
                    if time.time() < float(OldSizeSplit[2]) + 60*60*24:   # we keep size results for one day
                        SizeFile.write(OldSize)

        if not self.texfilename:
            for suffix in ("tex", "log", "size", "dvi", "eps", "texout", "texerr", "dvipsout", "dvipserr", ):
                try:
                    os.unlink(tempname + "." + suffix)
                except:
                    pass

        self._removeaddfiles(tempname)
        
        self.DoneRunTex = 1

    def bbox(self):
        self._run()
        return self.bbox

    def write(self, file):
        self._run()
        file.writelines(self.epsdata)
       
    def define(self, Cmd, *styleparams):
        if len(self.BoxCmds):
            raise TexDefAfterBoxError
        self.DoneRunTex = 0
        self.AllowedInstances(styleparams, [msghandler, ])
        self.DefCmds.append(_DefCmd(Cmd + "%\n",
                                    len(self.DefCmds)+ len(self.BoxCmds),
                                    self._getstack(),
                                    self.ExtractInstance(styleparams, msghandler, self.defaultmsghandler)))

    def _insertcmd(self, Cmd, *styleparams):
        if not len(self.BoxCmds):
            self._beginboxcmds()
            self.DefCmdsStr = reduce(lambda x,y: x + y.DefCmd, self.DefCmds, "")
        MyCmd = _BoxCmd(self.DefCmdsStr,
                        Cmd,
                        self.ExtractInstance(styleparams, style, style.text),
                        self.ExtractInstance(styleparams, fontsize, fontsize.normalsize),
                        self.ExtractInstance(styleparams, valign),
                        len(self.DefCmds)+ len(self.BoxCmds),
                        self._getstack(),
                        self.ExtractInstance(styleparams, msghandler, self.defaultmsghandler))
        if MyCmd not in self.BoxCmds:
            self.BoxCmds.append(MyCmd)
        for Cmd in self.BoxCmds:
            if Cmd == MyCmd:
                UseCmd = Cmd    # we could use MyCmd directly if we have just inserted it before
                                # (that's due to the side effect, that append doesn't make a copy of the element,
                                # but we ignore this here -- we don't want to depend on this side effect)
        return UseCmd

    def _text(self, x, y, Cmd, *styleparams):
        """print Cmd at (x, y) --- position parameters in postscipt points"""
        self.DoneRunTex = 0
        self.AllowedInstances(styleparams, [style, fontsize, halign, valign, direction, msghandler, color.color, ])
        self._insertcmd(Cmd, *styleparams).Put(x * 72.27 / 72.0,
                                               y * 72.27 / 72.0,
                                               self.ExtractInstance(styleparams, halign, halign.left),
                                               self.ExtractInstance(styleparams, direction, direction.horizontal),
                                               self.ExtractInstance(styleparams, color.color, color.grey.black))


    def text(self, x, y, Cmd, *styleparams):
        """print Cmd at (x, y)"""
        self._text(unit.topt(x), unit.topt(y), Cmd, *styleparams)

    def textwd(self, Cmd, *styleparams):
        """get width of Cmd"""
        self.DoneRunTex = 0
        self.AllowedInstances(styleparams, [style, fontsize, msghandler, ])
        return self._insertcmd(Cmd, *styleparams).Extent(_extent.wd, self.Sizes)

    def textht(self, Cmd, *styleparams):
        """get height of Cmd"""
        self.DoneRunTex = 0
        self.AllowedInstances(styleparams, [style, fontsize, valign, msghandler, ])
        return self._insertcmd(Cmd, *styleparams).Extent(_extent.ht, self.Sizes)

    def textdp(self, Cmd, *styleparams):
        """get depth of Cmd"""
        self.DoneRunTex = 0
        self.AllowedInstances(styleparams, [style, fontsize, valign, msghandler, ])
        return self._insertcmd(Cmd, *styleparams).Extent(_extent.dp, self.Sizes)


class tex(_tex):

    """tex class adds the specializations to _tex needed for tex"""
    
    def __init__(self, lts="10pt", **addargs):
        _tex.__init__(self, **addargs)
        # TODO: other ways for creating font sizes?
        LtsName = os.path.join(os.path.dirname(__file__), "lts", str(lts) + ".lts")
        self.define(open(LtsName, "r").read())
        self.define("\\newdimen\\linewidth%\n\\hsize0truein%\n\\vsize0truein%\n\\hoffset-1truein%\n\\voffset-1truein")

    def _beginboxcmds(self):
        pass

    def _endcmd(self):
        return "\\end\n"

    def _executetex(self, tempname):
        self._execute("tex %(t)s.tex > %(t)s.texout 2> %(t)s.texerr" % {"t": tempname})


class latex(_tex):

    """latex class adds the specializations to _tex needed for latex"""

    def __init__(self, docclass="article", docopt=None, auxfilename=None, **addargs):
        _tex.__init__(self, **addargs)
        self.auxfilename = auxfilename
        if docopt:
            self.define("\\documentclass[" + str(docopt) + "]{" + str(docclass) + "}")
        else:
            self.define("\\documentclass{" + str(docclass) + "}")
        self.define("\\hsize0truein%\n\\vsize0truein%\n\\hoffset-1truein%\n\\voffset-1truein")

    def _beginboxcmds(self):
        self.define("\\begin{document}")

    def _endcmd(self):
        return "\\end{document}\n"

    def _createaddfiles(self, tempname):
        if self.auxfilename is not None:
            writenew = 0
            try:
                os.rename(self.auxfilename + ".aux", tempname + ".aux")
            except OSError:
                writenew = 1
        else:
            writenew = 1
        if writenew:
            auxfile = open(tempname + ".aux", "w")
            auxfile.write("\\relax\n")
            auxfile.close()

    def _executetex(self, tempname):
        self._execute("latex %(t)s.tex > %(t)s.texout 2> %(t)s.texerr" % {"t": tempname})

    def _removeaddfiles(self, tempname):
        if self.auxfilename is not None:
            os.rename(tempname + ".aux", self.auxfilename + ".aux")
        else:
            os.unlink(tempname + ".aux")

