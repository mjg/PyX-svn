#!/usr/bin/env python

from const import *
import string

linecap_butt   = 0
linecap_round  = 1
linecap_square = 2

linejoin_miter = 0
linejoin_round = 1
linejoin_bevel = 2

linestyle_solid      = (linecap_butt,  [])
linestyle_dashed     = (linecap_butt,  [2])
linestyle_dotted     = (linecap_round, [0, 3])
linestyle_dashdotted = (linecap_round, [0, 3, 3, 3])

# PostScript-procedure definitions
# cf. file: 5002.EPSF_Spec_v3.0.pdf     

PSProlog = """
/rect {
  4 2 roll moveto 
  1 index 0 rlineto 
  0 exch rlineto 
  neg 0 rlineto 
  closepath 
} bind def
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
} bind def"""

unit_ps		= 1.0

unit_u2p	= 28.346456693*unit_ps
unit_v2p	= 28.346456693*unit_ps
unit_w2p	= 28.346456693*unit_ps

class canvas:

    PSCmds = [] 				# stores all PS commands of the canvas

    def __init__(self, base, width, height ):
        self.Width=width
        self.Height=height
	if type(base)==type(""):
	    self.BaseFilename = base
	    self.isPrimaryCanvas = 1
	else: 
	    if isinstance(base, canvas): 
	        self.isPrimaryCanvas = 0
	    else:
	        assert("base should be either a filename or a canvas")
        self.PSInit()

    
    def __del__(self):
        self.PSRun()
    
    def PSAddCmd(self, cmd):
        self.PSCmds = self.PSCmds + [ cmd ]
	
    def PSInit(self):
    	if self.isPrimaryCanvas:
           self.PSAddCmd("%!PS-Adobe-3.0 EPSF 3.0")
           self.PSAddCmd("%%BoundingBox: 0 0 %d %d" % (1000,1000)) # TODO: richtige Boundingbox!
           self.PSAddCmd("%%Creator: pyx 0.0.1") 
           self.PSAddCmd("%%Title: %s.eps" % self.BaseFilename) 
           # self.PSAddCmd("%%CreationDate: %s" % ) 
           self.PSAddCmd("%%EndComments") 
           self.PSAddCmd("%%BeginProlog") 
	   self.PSAddCmd(PSProlog)
           self.PSAddCmd("%%EndProlog") 

	   
        self.gsave()						# encapsulate canvas
	self.PSAddCmd("%f %f scale" % (1/unit_ps, 1/unit_ps))
        self.PSAddCmd("%f setlinewidth" % self.w2p(0.02))	# TODO: fixme

    def PSRun(self):
	self.grestore()						# canvas has been encapsulated
	
	if self.isPrimaryCanvas:
           try:
  	      PSFile = open(self.BaseFilename + ".eps", "w")
	   except IOError:
	      assert "cannot open output file"		# TODO: Fehlerbehandlung...
  	   for cmd in self.PSCmds:
	      PSFile.write("%s\n" % cmd)
	   PSFile.close()
        else:
  	   for cmd in self.PSCmds:			# maybe, we should be more efficient here
	      self.base.PSAddCmd(cmd)
	      
    def PSGetEPSBoundingBox(self, epsname):
    
        'returns bounding box of EPS file epsname as 4-tuple (llx, lly, urx, ury)'
	
        try:
	    epsfile=open(epsname,"r")
	except:
	    assert "cannot open EPS file"	# TODO: Fehlerbehandlung

        import re

	bbpattern = re.compile( r"^%%BoundingBox:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$" )

	while 1:
	    line=epsfile.readline()
	    if not line:
	        assert "bounding box not found in EPS file"
		raise IOError			# TODO: Fehlerbehandlung
	    if line=="%%EndComments\n": 
		# TODO: BoundingBox-Deklaration kann auch an Ende von Datei verschoben worden sein
	        assert "bounding box not found in EPS file"
		raise IOError			# TODO: Fehlerbehandlung
		
            bbmatch = bbpattern.match(line)
	    if bbmatch is not None:
	        (llx, lly, urx, ury) = map(int, bbmatch.groups())		# conversion strings->int
		break
        epsfile.close()
	return (llx, lly, urx, ury)

    def u2p(self, lengths):
    	if isnumber(lengths): 
	    return lengths*unit_u2p
	else: 
	    return tuple(map(lambda x:x*unit_u2p, lengths))
	
    def v2p(self, lengths):
    	if isnumber(lengths): 
	    return lengths*unit_v2p
	else: 
	    return tuple(map(lambda x:x*unit_v2p, lengths))
	
    def w2p(self, lengths):
    	if type(lengths)==type(0.0): 
	    return lengths*unit_w2p
	else: 
	    return tuple(map(lambda x:x*unit_w2p, lengths))
	
    def PSInsertEPS(self, x, y, epsname):
    
        'Insert EPS file epsname at current position'
	
	(llx, lly, urx, ury) = self.PSGetEPSBoundingBox(epsname)
	
        try:
	    epsfile=open(epsname,"r")
	except:
	    assert "cannot open EPS file"	# TODO: Fehlerbehandlung

	self.PSAddCmd("BeginEPSF")
	self.PSAddCmd("%f %f translate" % self.u2p((x, y)) ) 
	self.PSAddCmd("%f %f translate" % self.u2p((-llx, -lly)) )
	self.PSAddCmd("%f %f %f %f rect" % self.u2p((llx, lly, urx-llx,ury-lly)))
	self.PSAddCmd("clip newpath")
	self.PSAddCmd("%%BeginDocument: %s" % epsname)
	self.PSAddCmd(epsfile.read())  	
	self.PSAddCmd("%%EndDocument")
	self.PSAddCmd("EndEPSF")


    def stroke(self):
    	self.PSAddCmd("stroke")
	
    def newpath(self):
    	self.PSAddCmd("newpath")
	
    def closepath(self):
    	self.PSAddCmd("closepath")

    def draw(self,path):
        path.draw(self)

    def setlinecap(self, cap):
        #isnumber(cap)

	self.PSAddCmd("%d setlinecap" % cap)

    def setlinejoin(self, join):
        #isnumber(join)

	self.PSAddCmd("%d setlinejoin" % join)
	
    def setmiterlimit(self, limit):
        #isnumber(join)

	self.PSAddCmd("%f setmiterlimit" % limit)

    def setdash(self, pattern, offset=0):
    	patternstring=""
    	for element in pattern:
		patternstring=patternstring + `element` + " "
    	
    	self.PSAddCmd("[%s] %d setdash" % (patternstring, offset))

    def setlinestyle(self, style, offset=0):
        self.setlinecap(style[0])
	self.setdash   (style[1], offset)

    def gsave(self):
        self.PSAddCmd("gsave")
	
    def grestore(self):
        self.PSAddCmd("grestore")
    

if __name__=="__main__":
    c=canvas("example", 21, 29.7)

    from tex import *
    from path import *
    t=tex(c)

    #for x in range(11):
    #    amove(x,0)
    #    rline(0,20)
    #for y in range(21):
    #   amove(0,y)
    #   rline(10,0)

    c.draw(path( [moveto(1,1), 
                  lineto(2,2), 
                  moveto(1,2), 
                  lineto(2,1) ] 
		)
          )
    c.draw(line(1, 1, 1,2)) 

    print "Breite von 'Hello world!': ",t.textwd("Hello  world!")
    print "H�he von 'Hello world!': ",t.textht("Hello world!")
    print "H�he von 'Hello world!' in large: ",t.textht("Hello world!", size = large)
    print "H�he von 'Hello world!' in Large: ",t.textht("Hello world!", size = Large)
    print "H�he von 'Hello world' in huge: ",t.textht("Hello world!", size = huge)
    print "Tiefe von 'Hello world!': ",t.textdp("Hello world!")
    print "Tiefe von 'was mit q': ",t.textdp("was mit q")
    t.text(5, 1, "Hello world!")
    t.text(5, 2, "Hello world!", halign = center)
    t.text(5, 3, "Hello world!", halign = right)
    for angle in (-90,-80,-70,-60,-50,-40,-30,-20,-10,0,10,20,30,40,50,60,70,80,90):
        t.text(11+angle/10, 5, str(angle), angle = angle)
	t.text(11+angle/10, 6, str(angle), angle = angle, halign = center)
	t.text(11+angle/10, 7, str(angle), angle=angle, halign=right)
    for pos in range(1,21):
        t.text(pos, 7.5, ".")
   
    p=path([ moveto(5,12), 
             lineto(7,12), 
	     moveto(5,10), 
	     lineto(5,14), 
	     moveto(7,10), 
	     lineto(7,14)])
   
    c.setlinestyle(linestyle_dotted)
    t.text(5, 12, "a b c d e f g h i j k l m n o p q r s t u v w x y z", hsize = 2)
    c.draw(p)

    p.translate(5,0)
    c.setlinestyle(linestyle_dashdotted)
    t.text(10, 12, "a b c d e f g h i j k l m n o p q r s t u v w x y z", hsize = 2, valign = bottom)
    c.draw(p)
    
    t.TexRun()
