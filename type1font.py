#!/usr/bin/env python
# -*- coding: ISO-8859-1 -*-
#
#
# Copyright (C) 2005 J�rg Lehmann <joergl@users.sourceforge.net>
# Copyright (C) 2005 Andr� Wobst <wobsta@users.sourceforge.net>
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

import math, re
import canvas, pykpathsea, pswriter, pdfwriter

_PFB_ASCII = "\200\1"
_PFB_BIN = "\200\2"
_PFB_DONE = "\200\3"
_PFA = "%!"

_StandardEncodingMatch = re.compile(r"\b/Encoding\s+StandardEncoding\s+def\b")
#_FontBBoxMatch = re.compile(r"\bFontBBox\s*\{\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\}\s*readonly\s+def\b")
#_ItalicAngle = re.compile(r"\bItalicAngle\s+(-?\d+)\b")


def _pfblength(s):
    if len(s) != 4:
        raise ValueError("invalid string length")
    return (ord(s[0]) +
            ord(s[1])*256 +
            ord(s[2])*256*256 +
            ord(s[3])*256*256*256)

class type1font:

    def __init__(self, font):
        self.font = font
        # self.filename = pykpathsea.find_file("%s.%s" % (name, type), pykpathsea.kpse_type1_format)

        self.fontmapinfo = self.font.fontmap.get(self.font.name)
        self.filename = self.getfontfile()
        self.tfmfile = font.tfmfile

        fontfile = open(self.filename, "rb")
        self.fontdata = fontfile.read()
        fontfile.close()

        # split the font into its three main parts
        
        if self.fontdata[0:2] != _PFB_ASCII:
            raise RuntimeError("PFB_ASCII mark expected")
        self.length1 = _pfblength(self.fontdata[2:6])
        self.fontdata1 = self.fontdata[6:6+self.length1]
        
        if self.fontdata[6+self.length1:8+self.length1] != _PFB_BIN:
            raise RuntimeError("PFB_BIN mark expected")
        self.length2 = _pfblength(self.fontdata[8+self.length1:12+self.length1])
        self.fontdata2 = self.fontdata[12+self.length1:12+self.length1+self.length2]
        
        if self.fontdata[12+self.length1+self.length2:14+self.length1+self.length2] != _PFB_ASCII:
            raise RuntimeError("PFB_ASCII mark expected")
        self.length3 = _pfblength(self.fontdata[14+self.length1+self.length2:18+self.length1+self.length2])
        self.fontdata3 = self.fontdata[18+self.length1+self.length2:18+self.length1+self.length2+self.length3]
        
        if self.fontdata[18+self.length1+self.length2+self.length3:20+self.length1+self.length2+self.length3] != _PFB_DONE:
            raise RuntimeError("PFB_DONE mark expected")
        
        if len(self.fontdata) != 20 + self.length1 + self.length2 + self.length3:
            raise RuntimeError("end of pfb file expected")

        # The following code is a very crude way to obtain the information
        # required for the PDF font descritor.
        # As a simple heuristics we assume non-symbolic fonts if and only
        # if the Adobe standard encoding is used. All other font flags are
        # not specified here.
        if _StandardEncodingMatch.search(self.fontdata1):
            self.flags = 32
        else:
            self.flags = 4
        # self.fontbbox = map(int, _FontBBoxMatch(self.fontdata1))
        # self.italicangle = int(_ItalicAngleMatch(self.fontdata1))
        # self.ascent = self.fontbbox[3]
        # self.descent = self.fontbbox[1]
        # self.capheight = self.fontbbox[3]
        # self.stemv = (self.fontbbox[2] - self.fontbbox[0]) / 23
        self.fontbbox = (0,
                         -self.getdepth_pt(ord("y"))*1000/self.font.getsize_pt(),
                         self.getwidth_pt(ord("W"))*1000/self.font.getsize_pt(),
                         self.getheight_pt(ord("H"))*1000/self.font.getsize_pt())
        self.italicangle = -180/math.pi*math.atan(self.tfmfile.param[0]/65536.0)
        self.ascent = self.fontbbox[3]
        self.descent = self.fontbbox[1]
        self.capheight = self.getheight_pt(ord("h"))*1000/self.font.getsize_pt()
        self.vstem = self.getwidth_pt(ord("."))*1000/self.font.getsize_pt()/3

    def getfontfile(self):
        fontfilename = self.fontmapinfo.fontfile
        if fontfilename is None:
            return None
        else:
            return pykpathsea.find_file(fontfilename, pykpathsea.kpse_type1_format)

    def getbasepsname(self):
        return self.fontmapinfo.basepsname

    def getpsname(self):
        if self.fontmapinfo.reencodefont:
            return "%s-%s" % (self.fontmapinfo.basepsname, self.fontmapinfo.reencodefont)
        else:
            return self.fontmapinfo.basepsname
        
    def getencoding(self):
        return self.fontmapinfo.reencodefont

    def getencodingfile(self):
        return self.fontmapinfo.encodingfile

    # routines returning lengths as floats in PostScript points

    def getwidth_pt(self, charcode):
        return self.font._convert_tfm_to_pt(self.tfmfile.width[self.tfmfile.char_info[charcode].width_index])

    def getheight_pt(self, charcode):
        return self.font._convert_tfm_to_pt(self.tfmfile.height[self.tfmfile.char_info[charcode].height_index])

    def getdepth_pt(self, charcode):
        return self.font._convert_tfm_to_pt(self.tfmfile.depth[self.tfmfile.char_info[charcode].depth_index])

    def getitalic_pt(self, charcode):
        return self.font._convert_tfm_to_pt(self.tfmfile.italic[self.tfmfile.char_info[charcode].italic_index])


class text_pt(canvas.canvasitem):

    def __init__(self, x_pt, y_pt, type1font):
        self.type1font = type1font
        self.x_pt = x_pt
        self.y_pt = y_pt
        self.width_pt = 0
        self.height_pt = 0
        self.depth_pt = 0
        self.chars = []

    def addchar(self, char):
        self.width_pt += self.type1font.getwidth_pt(char)
        cheight_pt = self.type1font.getwidth_pt(char)
        if cheight_pt > self.height_pt:
            self.height_pt = cheight_pt
        cdepth_pt = self.type1font.getdepth_pt(char)
        if cdepth_pt > self.depth_pt:
            self.depth_pt = cdepth_pt
        self.chars.append(char)

    def bbox(self):
        return bbox.bbox_pt(self.x_pt, self.y_pt-self.depth_pt, self.x_pt+self.width_pt, self.y_pt+self.height_pt)

    def registerPS(self, registry):
        # note that we don't register PSfont as it is just a helper resource
        # which registers the needed components
        pswriter.PSfont(self.type1font, self.chars, registry)

    def registerPDF(self, registry):
        registry.add(pdfwriter.PDFfont(self.type1font, self.chars, registry))

    def outputPS(self, file):
        file.write("/%s %f selectfont\n" % (self.type1font.getpsname(), self.type1font.font.getsize_pt()))
        outstring = ""
        for char in self.chars:
            if char > 32 and char < 127 and chr(char) not in "()[]<>\\":
                ascii = "%s" % chr(char)
            else:
                ascii = "\\%03o" % char
            outstring += ascii
        file.write("%g %g moveto (%s) show\n" % (self.x_pt, self.y_pt, outstring))


    def outputPDF(self, file, writer, context):
        if ( context.font is None or 
             context.font.getpsname() != self.type1font.getpsname() or 
             context.font.font.getsize_pt() !=  self.type1font.font.getsize_pt() ):
            file.write("/%s %f Tf\n" % (self.type1font.getpsname(), self.type1font.font.getsize_pt()))
            context.font = self.type1font
        outstring = ""
        for char in self.chars:
            if char > 32 and char < 127 and chr(char) not in "()[]<>\\":
                ascii = "%s" % chr(char)
            else:
                ascii = "\\%03o" % char
            outstring += ascii
        file.write("1 0 0 1 %f %f Tm (%s) Tj\n" % (self.x_pt, self.y_pt, outstring))

