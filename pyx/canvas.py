#!/usr/bin/env python

from globex import *
from const import *

class Canvas(Globex):

    ExportMethods = [ "amove", "text", "textwd", "textht", "textdp" ]

    BaseFilename = "example"

    def __init__(self):
        self.PSInit()

    def TexCreateBoxCmd(self, texstr, parmode, valign):

        # we use two "{{" to ensure, that everything goes into the box
        CmdBegin = "\\setbox\\mybox=\\hbox{{"
        CmdEnd = "}}"

        if parmode != None:
             # TODO: check that parmode is a valid TeX length
             if valign == top or valign == None:
                  CmdBegin = CmdBegin + "\\begin{minipage}[t]{" + parmode + "}"
                  CmdEnd = "\\end{minipage}" + CmdEnd
             elif valign == center:
                  CmdBegin = CmdBegin + "\\begin{minipage}{" + parmode + "}"
                  CmdEnd = "\\end{minipage}" + CmdEnd
             elif valign == bottom:
                  CmdBegin = CmdBegin + "\\begin{minipage}[b]{" + parmode + "}"
                  CmdEnd = "\\end{minipage}" + CmdEnd
             else:
                  assert "valign unknown"
        else:
             if valign != None:
                  assert "parmode needed to use valign"
        
        Cmd = CmdBegin + texstr + CmdEnd + "\n"
        return Cmd
    
    def TexCopyBoxCmd(self, texstr, halign, angle):

        CmdBegin = ""
        CmdEnd = ""

        if angle != None and angle != 0:
            isnumber(angle)
            CmdBegin = CmdBegin + "\\begin{rotate}{" + str(angle) + "}"
            CmdEnd = "\\end{rotate}" + CmdEnd

        if halign != None:
            if halign == left:
                pass
            elif halign == center:
                CmdBegin = CmdBegin + "\\hbox{\\kern-.5\\wd\\mybox}"
            elif halign == right:
                CmdBegin = CmdBegin + "\\hbox{\\kern-\\wd\\mybox}"
            else:
                assert "halign unknown"

        Cmd = CmdBegin + "\\copy\\mybox" + CmdEnd
        return Cmd

    def TexHexMD5(self, texstr):
        import md5, string
        h = string.hexdigits
        r = ''
        s = md5.md5(self.TexInitStr + texstr).digest()
        for c in s:
            i = ord(c)
            r = r + h[(i >> 4) & 0xF] + h[i & 0xF]
        return r
        
    TexExpressions = [ ]
    TexInitStr = ""
    
    def TexAddToFile(self, Cmd):
        # TODO: store stack in markers to create detailed error messages
        MarkerBegin = "\\immediate\\write16{MarkerBegin}\n"
        MarkerEnd = "\\immediate\\write16{MarkerEnd}\n"

        Cmd = MarkerBegin + Cmd + MarkerEnd
        self.TexExpressions = self.TexExpressions + [ Cmd, ]

    def TexRun(self):

        import os

        file = open(self.BaseFilename + ".tex", "w")

        file.write("""\\nonstopmode
\\documentclass{article}
\\usepackage{rotating}
\\setlength{\\textheight}{29.7truecm}
\\setlength{\\textwidth}{21truecm}
\\setlength{\\topmargin}{0truecm}
\\setlength{\\headheight}{0truecm}
\\setlength{\\headsep}{0truecm}
\\setlength{\\marginparwidth}{0truecm}
\\setlength{\\marginparsep}{0truecm}
\\setlength{\\oddsidemargin}{0truecm}
\\setlength{\\evensidemargin}{0truecm}
\\setlength{\\hoffset}{-1truein}
\\setlength{\\voffset}{-1truein}
\\setlength{\\parindent}{0truecm}
\\pagestyle{empty}
\\immediate\\write16{MarkerBegin TexInitStr}
""" + self.TexInitStr + """
\\immediate\\write16{MarkerEnd TexInitStr}
\\begin{document}
\\newwrite\\myfile
\\newbox\\mybox
\\immediate\\openout\\myfile=""" + self.BaseFilename + """.size
\\setlength{\\unitlength}{1truecm}
\\begin{picture}(21,29.7)(0,0)
\\multiput(0,0)(1,0){22}{\\line(0,1){29.7}}
\\multiput(0,0)(0,1){30}{\\line(1,0){21}}\n""")

        file.writelines(self.TexExpressions)

        file.write("""\\end{picture}
\\immediate\\closeout\\myfile
\\end{document}\n""")
        file.close()

        # TODO: ordentliche Fehlerbehandlung,
        #       Auswertung der Marker auf Fehler beim TeX'en
        if os.system("latex " + self.BaseFilename + " > /dev/null 2>&1"):
            assert "LaTeX exit code not zero"
        
        # TODO: ordentliche Fehlerbehandlung,
        #       Schnittstelle zur Kommandozeile
        if os.system("dvips -E -o " + self.BaseFilename + ".tex.eps " +
                     self.BaseFilename + " > /dev/null 2>&1"):
            assert "dvips exit code not zero"
        
    TexResults = None

    def TexResult(self, Str):

        if self.TexResults == None:
            try:
                file = open(self.BaseFilename + ".size", "r")
                self.TexResults = file.readlines()
                file.close()
            except IOError: self.TexResults = [ ]

        for TexResult in self.TexResults:
            if TexResult[:len(Str)] == Str:
                return TexResult[len(Str):-1]
 
        return 1

    def text(self, texstr, halign=None, parmode=None, valign=None, angle=None):
        TexCreateBoxCmd = self.TexCreateBoxCmd(texstr, parmode, valign)
        self.TexAddToFile(TexCreateBoxCmd +
                          "\\put(" + str(self.x) + "," + str(self.y) + "){" +
                          self.TexCopyBoxCmd(texstr, halign, angle) + "}\n")

    def textwd(self, texstr, parmode=None):
        TexCreateBoxCmd = self.TexCreateBoxCmd(texstr, parmode, None)
        TexHexMD5=self.TexHexMD5(TexCreateBoxCmd)
        self.TexAddToFile(TexCreateBoxCmd +
                          "\\immediate\\write\\myfile{" + TexHexMD5 +
                          ":wd:\\the\\wd\\mybox}\n")
        return self.TexResult(TexHexMD5 + ":wd:")

    def textht(self, texstr, parmode=None, valign=None):
        TexCreateBoxCmd = self.TexCreateBoxCmd(texstr, parmode, valign)
        TexHexMD5=self.TexHexMD5(TexCreateBoxCmd)
        self.TexAddToFile(TexCreateBoxCmd +
                          "\\immediate\\write\\myfile{" + TexHexMD5 +
                          ":ht:\\the\\ht\\mybox}\n")
        return self.TexResult(TexHexMD5 + ":ht:")

    def textdp(self, texstr, parmode=None, valign=None):
        TexCreateBoxCmd = self.TexCreateBoxCmd(texstr, parmode, valign)
        TexHexMD5=self.TexHexMD5(TexCreateBoxCmd)
        self.TexAddToFile(TexCreateBoxCmd +
                          "\\immediate\\write\\myfile{" + TexHexMD5 +
                          ":dp:\\the\\dp\\mybox}\n")
        return self.TexResult(TexHexMD5 + ":dp:")

#
# PS code
#
	
    def PSInit(self):
        try:
	    self.PSFile = open(self.BaseFilename + ".ps", "w")
	except IOError:
	    print "cannot open output file"	# TODO: Fehlerbehandlung...
	    return
	
        self.PSFile.write("%!\n")

	# PostScript-procedure definitions
	# cf. file: 5002.EPSF_Spec_v3.0.pdf     
	self.PSFile.write("""
/BeginEPSF {
  /b4_Inc_state save def
  /dict_count countdictstack def
  /op_count count 1 sub def
  userdict begin
  /showpage { } def
  0 setgray 0 setlinecap
  1 setlinewidth 0 setlinejoin
  10 setmiterlimit [ ] 0 setdash newpath
  /languagelevel where
  {pop languagelevel
  1 ne
    {false setstrokeadjust false setoverprint
    } if
  } if
} bind def
/EndEPSF {
  count op_count sub {pop} repeat % Clean up stacks
  countdictstack dict_count sub {end} repeat
  b4_Inc_state restore
} bind def
""")
        
	self.PSFile.write("0.02 setlinewidth\n")
	self.PSFile.write("newpath\n")
	self.PSFile.write("0 0 moveto\n")

    def PSEnd(self):
    	self.PSFile.write("stroke\n")
	self.PSInsertEPS(self.BaseFilename + ".tex.eps")
	self.PSFile.close()
	
	
    def PSInsertEPS(self, epsname):
        try:
	    epsfile=open(epsname,"r")
	except:
	    print "cannot open EPS file"	# TODO: Fehlerbehandlung
	    return

	self.PSFile.write("BeginEPSF\n")
	self.PSFile.write(epsfile.read())  	
	self.PSFile.write("EndEPSF\n")

    def PScm2po(self, x, y=None): 
        convfaktor=28.452756
	
    	if y==None:
	    return convfaktor * x
	else:
	    return (convfaktor*x, convfaktor*y)
	    
    def amove(self,x,y):
        isnumber(x)
        isnumber(y)
        (self.x, self.y)=(x,y)
	self.PSFile.write("%d %d moveto\n" % self.PScm2po(x,y))
	
    


def canvas():
    DefaultCanvas=Canvas()
    DefaultCanvas.AddNamespace("DefaultCanvas",GetCallerGlobalNamespace())


if __name__=="__main__":
    canvas()



    amove(1,1)
    print "Breite von 'Hello world!': ",textwd("Hello world!")
    print "H�he von 'Hello world!': ",textht("Hello world!")
    print "Tiefe von 'Hello world!': ",textdp("Hello world!")
    print "Tiefe von 'was mit q': ",textdp("was mit q")
    amove(5,1)
    text("Hello world!")
    amove(5,2)
    text("\Large Hello world!",halign=center)
    amove(5,3)
    text("Hello world!",halign=right)
    for angle in (-90,-80,-70,-60,-50,-40,-30,-20,-10,0,10,20,30,40,50,60,70,80,90):
        amove(11+angle/10,5)
        text(str(angle),angle=angle)
	amove(11+angle/10,6)
	text(str(angle),angle=angle,halign=center)
	amove(11+angle/10,7)
	text(str(angle),angle=angle,halign=right)
    amove(5,12)
    text("Beispiel:\\begin{itemie}\\item$\\alpha$\\item$\\beta$\\item$\\gamma$\\end{itemize}",parmode="2cm")
    amove(10,12)
    text("Beispiel:\\begin{itemize}\\item$\\alpha$\\item$\\beta$\\item$\\gamma$\\end{itemize}",parmode="2cm",valign=center)
    amove(15,12)
    text("Beispiel:\\begin{itemize}\\item$\\alpha$\\item$\\beta$\\item$\\gamma$\\end{itemize}",parmode="2cm",valign=bottom)

    DefaultCanvas.TexRun()
    DefaultCanvas.PSEnd()
