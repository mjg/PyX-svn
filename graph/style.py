#!/usr/bin/env python
# -*- coding: ISO-8859-1 -*-
#
#
# Copyright (C) 2002-2004 J�rg Lehmann <joergl@users.sourceforge.net>
# Copyright (C) 2003-2004 Michael Schindler <m-schindler@users.sourceforge.net>
# Copyright (C) 2002-2004 Andr� Wobst <wobsta@users.sourceforge.net>
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


import re, math
from pyx import attr, deco, style, color, unit, canvas, path
from pyx import text as textmodule


class _style:
    """Interface class for graph styles

    Each graph style must support the methods described in this
    class. However, since a graph style might not need to perform
    actions on all the various events, it does not need to overwrite
    all methods of this base class (e.g. this class is not an abstract
    class in any respect).

    A style should never store private data by instance variables
    (i.e. accessing self), but it should use the styledata instance
    instead. A style instance can be used multiple times with different
    styledata instances at the very same time. The styledata instance
    acts as a data container and furthermore allows for sharing
    information across several styles.

    A style contains two class variables, which are not to be
    modified. provide is a of variable names a style provides via
    the styledata instance. This list should be used to find, whether
    all needs of subsequent styles are fullfilled. Otherwise the
    provider dictionary described below should list a proper style
    to be inserted. Contrary, need is a list of variable names the
    style needs to access in the styledata instance."""

    provide = [] # by default, we provide nothing
    need = [] # and do not depend on anything

    def columns(self, styledata, graph, columns):
        """Set column information

        This method is used setup the column information to be
        accessible to the style later on. The style should analyse
        the list of strings columns, which contain the column names
        of the data. The method should return a list of column names
        which the style will make use of."""
        return []

    def selectstyle(self, styledata, graph, selectindex, selecttotal):
        """Select stroke/fill attributes

        This method is called to allow for the selection of
        changable attributes of a style."""
        pass

    def adjustaxis(self, styledata, graph, column, data, index):
        """Adjust axis range

        This method is called in order to adjust the axis range to
        the provided data. Column is the name of the column (each
        style is subsequently called for all column names), data is
        a list of points and index is the index of the column within
        a point."""
        pass

    def initdrawpoints(self, styledata, graph):
        """Initialize drawing of data

        This method might be used to initialize the drawing of data."""
        pass

    def drawpoint(self, styledata, graph):
        """Draw data

        This method is called for each data point. The data is
        available in the dictionary styledata.data. The dictionary
        keys are the column names."""
        pass

    def donedrawpoints(self, styledata, graph):
        """Finalize drawing of data

        This method is called after the last data point was
        drawn using the drawpoint method above."""
        pass

    def key_pt(self, styledata, graph, x_pt, y_pt, width_pt, height_pt):
        """Draw a graph key

        Draw a graph key to graph."""
        pass


# provider is a dictionary, which maps styledata variable names
# to default styles, which provide a default way to create the
# corresponding styledata variable.

provider = {}


class _pos(_style):

    provide = ["vpos", "vposmissing", "vposavailable", "vposvalid"]

    def __init__(self, epsilon=1e-10):
        self.epsilon = epsilon

    def columns(self, styledata, graph, columns):
        styledata.pointposcolumns = []
        styledata.vposmissing = []
        for count, axisnames in enumerate(graph.axesnames):
            for axisname in axisnames:
                for column in columns:
                    if axisname == column:
                         styledata.pointposcolumns.append(column)
            if len(styledata.pointposcolumns) + len(styledata.vposmissing) > count+1:
                raise ValueError("multiple axes per graph dimension")
            elif len(styledata.pointposcolumns) + len(styledata.vposmissing) < count+1:
                styledata.vposmissing.append(count)
        return styledata.pointposcolumns

    def adjustaxis(self, styledata, graph, column, data, index):
        if column in styledata.pointposcolumns:
            graph.axes[column].adjustrange(data, index)

    def initdrawpoints(self, styledata, graph):
        styledata.vpos = [None]*(len(styledata.pointposcolumns) + len(styledata.vposmissing))
        styledata.pointpostmplist = [[column, index, graph.axes[column]] # temporarily used by drawpoint only
                                     for index, column in enumerate(styledata.pointposcolumns)]
        for missing in styledata.vposmissing:
            for pointpostmp in styledata.pointpostmplist:
                if pointpostmp[1] >= missing:
                    pointpostmp[1] += 1

    def drawpoint(self, styledata, graph):
        styledata.vposavailable = 1 # valid position (but might be outside of the graph)
        styledata.vposvalid = 1 # valid position inside the graph
        for column, index, axis in styledata.pointpostmplist:
            try:
                v = axis.convert(styledata.point[column])
            except (ArithmeticError, ValueError, TypeError):
                styledata.vposavailable = styledata.vposvalid = 0
                styledata.vpos[index] = None
            else:
                if v < - self.epsilon or v > 1 + self.epsilon:
                    styledata.vposvalid = 0
                styledata.vpos[index] = v


provider["vpos"] = provider["vposmissing"] = provider["vposavailable"] = provider["vposvalid"] = _pos()


class _range(_style):

    provide = ["vrange", "vrangemissing"]

    # internal bit masks
    mask_value = 1
    mask_min = 2
    mask_max = 4
    mask_dmin = 8
    mask_dmax = 16
    mask_d = 32

    def __init__(self, epsilon=1e-10):
        self.epsilon = epsilon

    def columns(self, styledata, graph, columns):
        def numberofbits(mask):
            if not mask:
                return 0
            if mask & 1:
                return numberofbits(mask >> 1) + 1
            else:
                return numberofbits(mask >> 1)
        usecolumns = []
        styledata.rangeposcolumns = []
        styledata.vrangemissing = []
        styledata.rangeposdeltacolumns = {} # temporarily used by adjustaxis only
        for count, axisnames in enumerate(graph.axesnames):
            for axisname in axisnames:
                mask = 0
                for column in columns:
                    addusecolumns = 1
                    if axisname == column:
                        mask += self.mask_value
                    elif axisname + "min" == column:
                        mask += self.mask_min
                    elif axisname + "max" == column:
                        mask += self.mask_max
                    elif "d" + axisname + "min" == column:
                        mask += self.mask_dmin
                    elif "d" + axisname + "max" == column:
                        mask += self.mask_dmax
                    elif "d" + axisname == column:
                        mask += self.mask_d
                    else:
                        addusecolumns = 0
                    if addusecolumns:
                        usecolumns.append(column)
                if mask & (self.mask_min | self.mask_max | self.mask_dmin | self.mask_dmax | self.mask_d):
                    if (numberofbits(mask & (self.mask_min | self.mask_dmin | self.mask_d)) > 1 or
                        numberofbits(mask & (self.mask_max | self.mask_dmax | self.mask_d)) > 1):
                        raise ValueError("multiple errorbar definition")
                    if mask & (self.mask_dmin | self.mask_dmax | self.mask_d):
                        if not (mask & self.mask_value):
                            raise ValueError("missing value for delta")
                        styledata.rangeposdeltacolumns[axisname] = {}
                    styledata.rangeposcolumns.append((axisname, mask))
                elif mask == self.mask_value:
                    usecolumns = usecolumns[:-1]
            if len(styledata.rangeposcolumns) + len(styledata.vrangemissing) > count+1:
                raise ValueError("multiple axes per graph dimension")
            elif len(styledata.rangeposcolumns) + len(styledata.vrangemissing) < count+1:
                styledata.vrangemissing.append(count)
        return usecolumns

    def adjustaxis(self, styledata, graph, column, data, index):
        if column in [c + "min" for c, m in styledata.rangeposcolumns if m & self.mask_min]:
            graph.axes[column[:-3]].adjustrange(data, index)
        if column in [c + "max" for c, m in styledata.rangeposcolumns if m & self.mask_max]:
            graph.axes[column[:-3]].adjustrange(data, index)

        # delta handling: fill rangeposdeltacolumns
        if column in [c for c, m in styledata.rangeposcolumns if m & (self.mask_dmin | self.mask_dmax | self.mask_d)]:
            styledata.rangeposdeltacolumns[column][self.mask_value] = data, index
        if column in ["d" + c + "min" for c, m in styledata.rangeposcolumns if m & self.mask_dmin]:
            styledata.rangeposdeltacolumns[column[1:-3]][self.mask_dmin] = data, index
        if column in ["d" + c + "max" for c, m in styledata.rangeposcolumns if m & self.mask_dmax]:
            styledata.rangeposdeltacolumns[column[1:-3]][self.mask_dmax] = data, index
        if column in ["d" + c for c, m in styledata.rangeposcolumns if m & self.mask_d]:
            styledata.rangeposdeltacolumns[column[1:]][self.mask_d] = data, index

        # delta handling: process rangeposdeltacolumns
        for c, d in styledata.rangeposdeltacolumns.items():
            if d.has_key(self.mask_value):
                for k in d.keys():
                    if k != self.mask_value:
                        if k & (self.mask_dmin | self.mask_d):
                            graph.axes[c].adjustrange(d[self.mask_value][0], d[self.mask_value][1],
                                                      deltamindata=d[k][0], deltaminindex=d[k][1])
                        if k & (self.mask_dmax | self.mask_d):
                            graph.axes[c].adjustrange(d[self.mask_value][0], d[self.mask_value][1],
                                                      deltamaxdata=d[k][0], deltamaxindex=d[k][1])
                        del d[k]

    def initdrawpoints(self, styledata, graph):
        styledata.vrange = [[None for x in range(2)] for y in styledata.rangeposcolumns + styledata.vrangemissing]
        styledata.rangepostmplist = [[column, mask, index, graph.axes[column]] # temporarily used by drawpoint only
                                     for index, (column, mask) in enumerate(styledata.rangeposcolumns)]
        for missing in styledata.vrangemissing:
            for rangepostmp in styledata.rangepostmplist:
                if rangepostmp[2] >= missing:
                    rangepostmp[2] += 1

    def drawpoint(self, styledata, graph):
        for column, mask, index, axis in styledata.rangepostmplist:
            try:
                if mask & self.mask_min:
                    styledata.vrange[index][0] = axis.convert(styledata.point[column + "min"])
                if mask & self.mask_dmin:
                    styledata.vrange[index][0] = axis.convert(styledata.point[column] - styledata.point["d" + column + "min"])
                if mask & self.mask_d:
                    styledata.vrange[index][0] = axis.convert(styledata.point[column] - styledata.point["d" + column])
            except (ArithmeticError, ValueError, TypeError):
                styledata.vrange[index][0] = None
            try:
                if mask & self.mask_max:
                    styledata.vrange[index][1] = axis.convert(styledata.point[column + "max"])
                if mask & self.mask_dmax:
                    styledata.vrange[index][1] = axis.convert(styledata.point[column] + styledata.point["d" + column + "max"])
                if mask & self.mask_d:
                    styledata.vrange[index][1] = axis.convert(styledata.point[column] + styledata.point["d" + column])
            except (ArithmeticError, ValueError, TypeError):
                styledata.vrange[index][1] = None

            # some range checks for data consistency
            if (styledata.vrange[index][0] is not None and styledata.vrange[index][1] is not None and
                styledata.vrange[index][0] > styledata.vrange[index][1] + self.epsilon):
                raise ValueError("negative errorbar range")
            if (styledata.vrange[index][0] is not None and styledata.vpos[index] is not None and
                styledata.vrange[index][0] > styledata.vpos[index] + self.epsilon):
                raise ValueError("negative minimum errorbar")
            if (styledata.vrange[index][1] is not None and styledata.vpos[index] is not None and
                styledata.vrange[index][1] < styledata.vpos[index] - self.epsilon):
                raise ValueError("negative maximum errorbar")


provider["vrange"] = provider["vrangemissing"] = _range()


def _crosssymbol(c, x_pt, y_pt, size_pt, attrs):
    c.draw(path.path(path.moveto_pt(x_pt-0.5*size_pt, y_pt-0.5*size_pt),
                     path.lineto_pt(x_pt+0.5*size_pt, y_pt+0.5*size_pt),
                     path.moveto_pt(x_pt-0.5*size_pt, y_pt+0.5*size_pt),
                     path.lineto_pt(x_pt+0.5*size_pt, y_pt-0.5*size_pt)), attrs)

def _plussymbol(c, x_pt, y_pt, size_pt, attrs):
    c.draw(path.path(path.moveto_pt(x_pt-0.707106781*size_pt, y_pt),
                     path.lineto_pt(x_pt+0.707106781*size_pt, y_pt),
                     path.moveto_pt(x_pt, y_pt-0.707106781*size_pt),
                     path.lineto_pt(x_pt, y_pt+0.707106781*size_pt)), attrs)

def _squaresymbol(c, x_pt, y_pt, size_pt, attrs):
    c.draw(path.path(path.moveto_pt(x_pt-0.5*size_pt, y_pt-0.5*size_pt),
                     path.lineto_pt(x_pt+0.5*size_pt, y_pt-0.5*size_pt),
                     path.lineto_pt(x_pt+0.5*size_pt, y_pt+0.5*size_pt),
                     path.lineto_pt(x_pt-0.5*size_pt, y_pt+0.5*size_pt),
                     path.closepath()), attrs)

def _trianglesymbol(c, x_pt, y_pt, size_pt, attrs):
    c.draw(path.path(path.moveto_pt(x_pt-0.759835685*size_pt, y_pt-0.438691337*size_pt),
                     path.lineto_pt(x_pt+0.759835685*size_pt, y_pt-0.438691337*size_pt),
                     path.lineto_pt(x_pt, y_pt+0.877382675*size_pt),
                     path.closepath()), attrs)

def _circlesymbol(c, x_pt, y_pt, size_pt, attrs):
    c.draw(path.path(path.arc_pt(x_pt, y_pt, 0.564189583*size_pt, 0, 360),
                     path.closepath()), attrs)

def _diamondsymbol(c, x_pt, y_pt, size_pt, attrs):
    c.draw(path.path(path.moveto_pt(x_pt-0.537284965*size_pt, y_pt),
                     path.lineto_pt(x_pt, y_pt-0.930604859*size_pt),
                     path.lineto_pt(x_pt+0.537284965*size_pt, y_pt),
                     path.lineto_pt(x_pt, y_pt+0.930604859*size_pt),
                     path.closepath()), attrs)


class _styleneedingpointpos(_style):

    need = ["vposmissing"]

    def columns(self, styledata, graph, columns):
        if len(styledata.vposmissing):
            raise ValueError("position columns incomplete")
        return []


class symbol(_styleneedingpointpos):

    need = ["vpos", "vposmissing", "vposvalid"]

    # insert symbols like staticmethods
    cross = _crosssymbol
    plus = _plussymbol
    square = _squaresymbol
    triangle = _trianglesymbol
    circle = _circlesymbol
    diamond = _diamondsymbol

    changecross = attr.changelist([cross, plus, square, triangle, circle, diamond])
    changeplus = attr.changelist([plus, square, triangle, circle, diamond, cross])
    changesquare = attr.changelist([square, triangle, circle, diamond, cross, plus])
    changetriangle = attr.changelist([triangle, circle, diamond, cross, plus, square])
    changecircle = attr.changelist([circle, diamond, cross, plus, square, triangle])
    changediamond = attr.changelist([diamond, cross, plus, square, triangle, circle])
    changesquaretwice = attr.changelist([square, square, triangle, triangle, circle, circle, diamond, diamond])
    changetriangletwice = attr.changelist([triangle, triangle, circle, circle, diamond, diamond, square, square])
    changecircletwice = attr.changelist([circle, circle, diamond, diamond, square, square, triangle, triangle])
    changediamondtwice = attr.changelist([diamond, diamond, square, square, triangle, triangle, circle, circle])

    changestrokedfilled = attr.changelist([deco.stroked, deco.filled])
    changefilledstroked = attr.changelist([deco.filled, deco.stroked])

    defaultsymbolattrs = [deco.stroked]

    def __init__(self, symbol=changecross, size=0.2*unit.v_cm, symbolattrs=[]):
        self.symbol = symbol
        self.size = size
        self.symbolattrs = symbolattrs

    def selectstyle(self, styledata, graph, selectindex, selecttotal):
        styledata.symbol = attr.selectattr(self.symbol, selectindex, selecttotal)
        styledata.size_pt = unit.topt(attr.selectattr(self.size, selectindex, selecttotal))
        if self.symbolattrs is not None:
            styledata.symbolattrs = attr.selectattrs(self.defaultsymbolattrs + self.symbolattrs, selectindex, selecttotal)
        else:
            styledata.symbolattrs = None

    def initdrawpoints(self, styledata, graph):
        styledata.symbolcanvas = graph.insert(canvas.canvas())

    def drawpoint(self, styledata, graph):
        if styledata.vposvalid and styledata.symbolattrs is not None:
            xpos, ypos = graph.vpos_pt(*styledata.vpos)
            styledata.symbol(styledata.symbolcanvas, xpos, ypos, styledata.size_pt, styledata.symbolattrs)

    def key_pt(self, styledata, graph, x_pt, y_pt, width_pt, height_pt):
        if styledata.symbolattrs is not None:
            styledata.symbol(graph, x_pt+0.5*width_pt, y_pt+0.5*height_pt, styledata.size_pt, styledata.symbolattrs)


class line(_styleneedingpointpos):

    need = ["vpos", "vposmissing", "vposavailable", "vposvalid"]

    changelinestyle = attr.changelist([style.linestyle.solid,
                                       style.linestyle.dashed,
                                       style.linestyle.dotted,
                                       style.linestyle.dashdotted])

    defaultlineattrs = [changelinestyle]

    def __init__(self, lineattrs=[]):
        self.lineattrs = lineattrs

    def selectstyle(self, styledata, graph, selectindex, selecttotal):
        styledata.lineattrs = attr.selectattrs(self.defaultlineattrs + self.lineattrs, selectindex, selecttotal)

    def initdrawpoints(self, styledata, graph):
        styledata.linecanvas = graph.insert(canvas.canvas())
        if styledata.lineattrs is not None:
            styledata.linecanvas.set(styledata.lineattrs)
        styledata.path = path.path()
        styledata.linebasepoints = []
        styledata.lastvpos = None

    def addpointstopath(self, styledata):
        # add baselinepoints to styledata.path
        if len(styledata.linebasepoints) > 1:
            styledata.path.append(path.moveto_pt(*styledata.linebasepoints[0]))
            if len(styledata.linebasepoints) > 2:
                styledata.path.append(path.multilineto_pt(styledata.linebasepoints[1:]))
            else:
                styledata.path.append(path.lineto_pt(*styledata.linebasepoints[1]))
        styledata.linebasepoints = []

    def drawpoint(self, styledata, graph):
        # append linebasepoints
        if styledata.vposavailable:
            if len(styledata.linebasepoints):
                # the last point was inside the graph
                if styledata.vposvalid: # shortcut for the common case
                    styledata.linebasepoints.append(graph.vpos_pt(*styledata.vpos))
                else:
                    # cut end
                    cut = 1
                    for vstart, vend in zip(styledata.lastvpos, styledata.vpos):
                        newcut = None
                        if vend > 1:
                            # 1 = vstart + (vend - vstart) * cut
                            try:
                                newcut = (1 - vstart)/(vend - vstart)
                            except ArithmeticError:
                                break
                        if vend < 0:
                            # 0 = vstart + (vend - vstart) * cut
                            try:
                                newcut = - vstart/(vend - vstart)
                            except ArithmeticError:
                                break
                        if newcut is not None and newcut < cut:
                            cut = newcut
                    else:
                        cutvpos = []
                        for vstart, vend in zip(styledata.lastvpos, styledata.vpos):
                            cutvpos.append(vstart + (vend - vstart) * cut)
                        styledata.linebasepoints.append(styledata.graph.vpos_pt(*cutvpos))
                    self.addpointstopath(styledata)
            else:
                # the last point was outside the graph
                if styledata.lastvpos is not None:
                    if styledata.vposvalid:
                        # cut beginning
                        cut = 0
                        for vstart, vend in zip(styledata.lastvpos, styledata.vpos):
                            newcut = None
                            if vstart > 1:
                                # 1 = vstart + (vend - vstart) * cut
                                try:
                                    newcut = (1 - vstart)/(vend - vstart)
                                except ArithmeticError:
                                    break
                            if vstart < 0:
                                # 0 = vstart + (vend - vstart) * cut
                                try:
                                    newcut = - vstart/(vend - vstart)
                                except ArithmeticError:
                                    break
                            if newcut is not None and newcut > cut:
                                cut = newcut
                        else:
                            cutvpos = []
                            for vstart, vend in zip(styledata.lastvpos, styledata.vpos):
                                cutvpos.append(vstart + (vend - vstart) * cut)
                            styledata.linebasepoints.append(graph.vpos_pt(*cutvpos))
                            styledata.linebasepoints.append(graph.vpos_pt(*styledata.vpos))
                    else:
                        # sometimes cut beginning and end
                        cutfrom = 0
                        cutto = 1
                        for vstart, vend in zip(styledata.lastvpos, styledata.vpos):
                            newcutfrom = None
                            if vstart > 1:
                                if vend > 1:
                                    break
                                # 1 = vstart + (vend - vstart) * cutfrom
                                try:
                                    newcutfrom = (1 - vstart)/(vend - vstart)
                                except ArithmeticError:
                                    break
                            if vstart < 0:
                                if vend < 0:
                                    break
                                # 0 = vstart + (vend - vstart) * cutfrom
                                try:
                                    newcutfrom = - vstart/(vend - vstart)
                                except ArithmeticError:
                                    break
                            if newcutfrom is not None and newcutfrom > cutfrom:
                                cutfrom = newcutfrom
                            newcutto = None
                            if vend > 1:
                                # 1 = vstart + (vend - vstart) * cutto
                                try:
                                    newcutto = (1 - vstart)/(vend - vstart)
                                except ArithmeticError:
                                    break
                            if vend < 0:
                                # 0 = vstart + (vend - vstart) * cutto
                                try:
                                    newcutto = - vstart/(vend - vstart)
                                except ArithmeticError:
                                    break
                            if newcutto is not None and newcutto < cutto:
                                cutto = newcutto
                        else:
                            if cutfrom < cutto:
                                cutfromvpos = []
                                cuttovpos = []
                                for vstart, vend in zip(styledata.lastvpos, styledata.vpos):
                                    cutfromvpos.append(vstart + (vend - vstart) * cutfrom)
                                    cuttovpos.append(vstart + (vend - vstart) * cutto)
                                styledata.linebasepoints.append(styledata.graph.vpos_pt(*cutfromvpos))
                                styledata.linebasepoints.append(styledata.graph.vpos_pt(*cuttovpos))
                                self.addpointstopath(styledata)
            styledata.lastvpos = styledata.vpos[:]
        else:
            if len(styledata.linebasepoints) > 1:
                self.addpointstopath(styledata)
            styledata.lastvpos = None

    def donedrawpoints(self, styledata, graph):
        if len(styledata.linebasepoints) > 1:
            self.addpointstopath(styledata)
        if styledata.lineattrs is not None and len(styledata.path.path):
            styledata.linecanvas.stroke(styledata.path)

    def key_pt(self, styledata, graph, x_pt, y_pt, width_pt, height_pt):
        if styledata.lineattrs is not None:
            graph.stroke(path.line_pt(x_pt, y_pt+0.5*height_pt, x_pt+width_pt, y_pt+0.5*height_pt), styledata.lineattrs)


class errorbar(_style):

    need = ["vpos", "vposmissing", "vposavailable", "vposvalid", "vrange", "vrangemissing"]

    defaulterrorbarattrs = []

    def __init__(self, size=0.1*unit.v_cm,
                       errorbarattrs=[],
                       epsilon=1e-10):
        self.size = size
        self.errorbarattrs = errorbarattrs
        self.epsilon = epsilon

    def columns(self, styledata, graph, columns):
        for i in styledata.vposmissing:
            if i in styledata.vrangemissing:
                raise ValueError("position and range for a graph dimension missing")
        return []

    def selectstyle(self, styledata, graph, selectindex, selecttotal):
        styledata.errorsize_pt = unit.topt(attr.selectattr(self.size, selectindex, selecttotal))
        styledata.errorbarattrs = attr.selectattrs(self.defaulterrorbarattrs + self.errorbarattrs, selectindex, selecttotal)

    def initdrawpoints(self, styledata, graph):
        styledata.errorbarcanvas = graph.insert(canvas.canvas())
        if styledata.errorbarattrs is not None:
            styledata.errorbarcanvas.set(styledata.errorbarattrs)
        styledata.dimensionlist = range(len(styledata.vpos))

    def drawpoint(self, styledata, graph):
        if styledata.errorbarattrs is None:
            return
        for i in styledata.dimensionlist:
            for j in styledata.dimensionlist:
                if (i != j and
                    (styledata.vpos[j] is None or
                     styledata.vpos[j] < -self.epsilon or
                     styledata.vpos[j] > 1+self.epsilon)):
                    break
            else:
                if ((styledata.vrange[i][0] is None and styledata.vpos[i] is None) or
                    (styledata.vrange[i][1] is None and styledata.vpos[i] is None) or
                    (styledata.vrange[i][0] is None and styledata.vrange[i][1] is None)):
                    continue
                vminpos = styledata.vpos[:]
                if styledata.vrange[i][0] is not None:
                    vminpos[i] = styledata.vrange[i][0]
                    mincap = 1
                else:
                    mincap = 0
                if vminpos[i] > 1+self.epsilon:
                    continue
                if vminpos[i] < -self.epsilon:
                    vminpos[i] = 0
                    mincap = 0
                vmaxpos = styledata.vpos[:]
                if styledata.vrange[i][1] is not None:
                    vmaxpos[i] = styledata.vrange[i][1]
                    maxcap = 1
                else:
                    maxcap = 0
                if vmaxpos[i] < -self.epsilon:
                    continue
                if vmaxpos[i] > 1+self.epsilon:
                    vmaxpos[i] = 1
                    maxcap = 0
                styledata.errorbarcanvas.stroke(graph.vgeodesic(*(vminpos + vmaxpos)))
                for j in styledata.dimensionlist:
                    if i != j:
                        if mincap:
                            styledata.errorbarcanvas.stroke(graph.vcap_pt(j, styledata.errorsize_pt, *vminpos))
                        if maxcap:
                            styledata.errorbarcanvas.stroke(graph.vcap_pt(j, styledata.errorsize_pt, *vmaxpos))


# not yet ported to the new style scheme
# 
# class text(symbol):
# 
#     defaulttextattrs = [textmodule.halign.center, textmodule.vshift.mathaxis]
# 
#     def __init__(self, textdx=0*unit.v_cm, textdy=0.3*unit.v_cm, textattrs=[], **kwargs):
#         self.textdx = textdx
#         self.textdy = textdy
#         self.textattrs = textattrs
#         symbol.__init__(self, **kwargs)
# 
#     def setdata(self, graph, columns, styledata):
#         columns = columns.copy()
#         styledata.textindex = columns["text"]
#         del columns["text"]
#         return symbol.setdata(self, graph, columns, styledata)
# 
#     def selectstyle(self, selectindex, selecttotal, styledata):
#         if self.textattrs is not None:
#             styledata.textattrs = attr.selectattrs(self.defaulttextattrs + self.textattrs, selectindex, selecttotal)
#         else:
#             styledata.textattrs = None
#         symbol.selectstyle(self, selectindex, selecttotal, styledata)
# 
#     def drawsymbol_pt(self, c, x, y, styledata, point=None):
#         symbol.drawsymbol_pt(self, c, x, y, styledata, point)
#         if None not in (x, y, point[styledata.textindex]) and styledata.textattrs is not None:
#             c.text_pt(x + styledata.textdx_pt, y + styledata.textdy_pt, str(point[styledata.textindex]), styledata.textattrs)
# 
#     def drawpoints(self, points, graph, styledata):
#         styledata.textdx_pt = unit.topt(self.textdx)
#         styledata.textdy_pt = unit.topt(self.textdy)
#         symbol.drawpoints(self, points, graph, styledata)
# 
# 
# class arrow(_style):
# 
#     defaultlineattrs = []
#     defaultarrowattrs = []
# 
#     def __init__(self, linelength=0.25*unit.v_cm, arrowsize=0.15*unit.v_cm, lineattrs=[], arrowattrs=[], epsilon=1e-10):
#         self.linelength = linelength
#         self.arrowsize = arrowsize
#         self.lineattrs = lineattrs
#         self.arrowattrs = arrowattrs
#         self.epsilon = epsilon
# 
#     def setdata(self, graph, columns, styledata):
#         if len(graph.axisnames) != 2:
#             raise TypeError("arrow style restricted on two-dimensional graphs")
#         columns = columns.copy()
#         styledata.xaxis, styledata.xindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)$" % graph.axisnames[0]))
#         styledata.yaxis, styledata.yindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)$" % graph.axisnames[1]))
#         styledata.sizeindex = columns["size"]
#         del columns["size"]
#         styledata.angleindex = columns["angle"]
#         del columns["angle"]
#         return columns
# 
#     def adjustaxes(self, points, columns, styledata):
#         if styledata.xindex in columns:
#             styledata.xaxis.adjustrange(points, styledata.xindex)
#         if styledata.yindex in columns:
#             styledata.yaxis.adjustrange(points, styledata.yindex)
# 
#     def selectstyle(self, selectindex, selecttotal, styledata):
#         if self.lineattrs is not None:
#             styledata.lineattrs = attr.selectattrs(self.defaultlineattrs + self.lineattrs, selectindex, selecttotal)
#         else:
#             styledata.lineattrs = None
#         if self.arrowattrs is not None:
#             styledata.arrowattrs = attr.selectattrs(self.defaultarrowattrs + self.arrowattrs, selectindex, selecttotal)
#         else:
#             styledata.arrowattrs = None
# 
#     def drawpoints(self, points, graph, styledata):
#         if styledata.lineattrs is not None and styledata.arrowattrs is not None:
#             linelength_pt = unit.topt(self.linelength)
#             for point in points:
#                 xpos, ypos = graph.pos_pt(point[styledata.xindex], point[styledata.yindex], xaxis=styledata.xaxis, yaxis=styledata.yaxis)
#                 if point[styledata.sizeindex] > self.epsilon:
#                     dx = math.cos(point[styledata.angleindex]*math.pi/180)
#                     dy = math.sin(point[styledata.angleindex]*math.pi/180)
#                     x1 = xpos-0.5*dx*linelength_pt*point[styledata.sizeindex]
#                     y1 = ypos-0.5*dy*linelength_pt*point[styledata.sizeindex]
#                     x2 = xpos+0.5*dx*linelength_pt*point[styledata.sizeindex]
#                     y2 = ypos+0.5*dy*linelength_pt*point[styledata.sizeindex]
#                     graph.stroke(path.line_pt(x1, y1, x2, y2), styledata.lineattrs +
#                                  [deco.earrow(styledata.arrowattrs, size=self.arrowsize*point[styledata.sizeindex])])
# 
# 
# class rect(_style):
# 
#     def __init__(self, palette=color.palette.Gray):
#         self.palette = palette
# 
#     def setdata(self, graph, columns, styledata):
#         if len(graph.axisnames) != 2:
#             raise TypeError("arrow style restricted on two-dimensional graphs")
#         columns = columns.copy()
#         styledata.xaxis, styledata.xminindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)min$" % graph.axisnames[0]))
#         styledata.yaxis, styledata.yminindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)min$" % graph.axisnames[1]))
#         xaxis, styledata.xmaxindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)max$" % graph.axisnames[0]))
#         yaxis, styledata.ymaxindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)max$" % graph.axisnames[1]))
#         if xaxis != styledata.xaxis or yaxis != styledata.yaxis:
#             raise ValueError("min/max values should use the same axes")
#         styledata.colorindex = columns["color"]
#         del columns["color"]
#         return columns
# 
#     def selectstyle(self, selectindex, selecttotal, styledata):
#         pass
# 
#     def adjustaxes(self, points, columns, styledata):
#         if styledata.xminindex in columns:
#             styledata.xaxis.adjustrange(points, styledata.xminindex)
#         if styledata.xmaxindex in columns:
#             styledata.xaxis.adjustrange(points, styledata.xmaxindex)
#         if styledata.yminindex in columns:
#             styledata.yaxis.adjustrange(points, styledata.yminindex)
#         if styledata.ymaxindex in columns:
#             styledata.yaxis.adjustrange(points, styledata.ymaxindex)
# 
#     def drawpoints(self, points, graph, styledata):
#         # TODO: bbox shortcut
#         c = graph.insert(canvas.canvas())
#         lastcolorvalue = None
#         for point in points:
#             try:
#                 xvmin = styledata.xaxis.convert(point[styledata.xminindex])
#                 xvmax = styledata.xaxis.convert(point[styledata.xmaxindex])
#                 yvmin = styledata.yaxis.convert(point[styledata.yminindex])
#                 yvmax = styledata.yaxis.convert(point[styledata.ymaxindex])
#                 colorvalue = point[styledata.colorindex]
#                 if colorvalue != lastcolorvalue:
#                     color = self.palette.getcolor(point[styledata.colorindex])
#             except:
#                 continue
#             if ((xvmin < 0 and xvmax < 0) or (xvmin > 1 and xvmax > 1) or
#                 (yvmin < 0 and yvmax < 0) or (yvmin > 1 and yvmax > 1)):
#                 continue
#             if xvmin < 0:
#                 xvmin = 0
#             elif xvmin > 1:
#                 xvmin = 1
#             if xvmax < 0:
#                 xvmax = 0
#             elif xvmax > 1:
#                 xvmax = 1
#             if yvmin < 0:
#                 yvmin = 0
#             elif yvmin > 1:
#                 yvmin = 1
#             if yvmax < 0:
#                 yvmax = 0
#             elif yvmax > 1:
#                 yvmax = 1
#             p = graph.vgeodesic(xvmin, yvmin, xvmax, yvmin)
#             p.append(graph.vgeodesic_el(xvmax, yvmin, xvmax, yvmax))
#             p.append(graph.vgeodesic_el(xvmax, yvmax, xvmin, yvmax))
#             p.append(graph.vgeodesic_el(xvmin, yvmax, xvmin, yvmin))
#             p.append(path.closepath())
#             if colorvalue != lastcolorvalue:
#                 c.set([color])
#             c.fill(p)
# 
# 
# class bar(_style):
# 
#     defaultfrompathattrs = []
#     defaultbarattrs = [color.palette.Rainbow, deco.stroked([color.gray.black])]
# 
#     def __init__(self, fromvalue=None, frompathattrs=[], barattrs=[], subnames=None, epsilon=1e-10):
#         self.fromvalue = fromvalue
#         self.frompathattrs = frompathattrs
#         self.barattrs = barattrs
#         self.subnames = subnames
#         self.epsilon = epsilon
# 
#     def setdata(self, graph, columns, styledata):
#         # TODO: remove limitation to 2d graphs
#         if len(graph.axisnames) != 2:
#             raise TypeError("arrow style currently restricted on two-dimensional graphs")
#         columns = columns.copy()
#         xvalue = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)$" % graph.axisnames[0]))
#         yvalue = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)$" % graph.axisnames[1]))
#         if (xvalue is None and yvalue is None) or (xvalue is not None and yvalue is not None):
#             raise TypeError("must specify exactly one value axis")
#         if xvalue is not None:
#             styledata.valuepos = 0
#             styledata.nameaxis, styledata.nameindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)name$" % graph.axisnames[1]))
#             styledata.valueaxis = xvalue[0]
#             styledata.valueindices = [xvalue[1]]
#         else:
#             styledata.valuepos = 1
#             styledata.nameaxis, styledata.nameindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)name$" % graph.axisnames[0]))
#             styledata.valueaxis = yvalue[0]
#             styledata.valueindices = [yvalue[1]]
#         i = 1
#         while 1:
#             try:
#                 valueaxis, valueindex = _style.setdatapattern(self, graph, columns, re.compile(r"(%s([2-9]|[1-9][0-9]+)?)stack%i$" % (graph.axisnames[styledata.valuepos], i)))
#             except:
#                 break
#             if styledata.valueaxis != valueaxis:
#                 raise ValueError("different value axes for stacked bars")
#             styledata.valueindices.append(valueindex)
#             i += 1
#         return columns
# 
#     def selectstyle(self, selectindex, selecttotal, styledata):
#         if selectindex:
#             styledata.frompathattrs = None
#         else:
#             styledata.frompathattrs = self.defaultfrompathattrs + self.frompathattrs
#         if selecttotal > 1:
#             if self.barattrs is not None:
#                 styledata.barattrs = attr.selectattrs(self.defaultbarattrs + self.barattrs, selectindex, selecttotal)
#             else:
#                 styledata.barattrs = None
#         else:
#             styledata.barattrs = self.defaultbarattrs + self.barattrs
#         styledata.selectindex = selectindex
#         styledata.selecttotal = selecttotal
#         if styledata.selecttotal != 1 and self.subnames is not None:
#             raise ValueError("subnames not allowed when iterating over bars")
# 
#     def adjustaxes(self, points, columns, styledata):
#         if styledata.nameindex in columns:
#             if styledata.selecttotal == 1:
#                 styledata.nameaxis.adjustrange(points, styledata.nameindex, subnames=self.subnames)
#             else:
#                 for i in range(styledata.selecttotal):
#                     styledata.nameaxis.adjustrange(points, styledata.nameindex, subnames=[i])
#         for valueindex in styledata.valueindices:
#             if valueindex in columns:
#                 styledata.valueaxis.adjustrange(points, valueindex)
# 
#     def drawpoints(self, points, graph, styledata):
#         if self.fromvalue is not None:
#             vfromvalue = styledata.valueaxis.convert(self.fromvalue)
#             if vfromvalue < -self.epsilon:
#                 vfromvalue = 0
#             if vfromvalue > 1 + self.epsilon:
#                 vfromvalue = 1
#             if styledata.frompathattrs is not None and vfromvalue > self.epsilon and vfromvalue < 1 - self.epsilon:
#                 if styledata.valuepos:
#                     p = graph.vgeodesic(0, vfromvalue, 1, vfromvalue)
#                 else:
#                     p = graph.vgeodesic(vfromvalue, 0, vfromvalue, 1)
#                 graph.stroke(p, styledata.frompathattrs)
#         else:
#             vfromvalue = 0
#         l = len(styledata.valueindices)
#         if l > 1:
#             barattrslist = []
#             for i in range(l):
#                 barattrslist.append(attr.selectattrs(styledata.barattrs, i, l))
#         else:
#             barattrslist = [styledata.barattrs]
#         for point in points:
#             vvaluemax = vfromvalue
#             for valueindex, barattrs in zip(styledata.valueindices, barattrslist):
#                 vvaluemin = vvaluemax
#                 try:
#                     vvaluemax = styledata.valueaxis.convert(point[valueindex])
#                 except:
#                     continue
# 
#                 if styledata.selecttotal == 1:
#                     try:
#                         vnamemin = styledata.nameaxis.convert((point[styledata.nameindex], 0))
#                     except:
#                         continue
#                     try:
#                         vnamemax = styledata.nameaxis.convert((point[styledata.nameindex], 1))
#                     except:
#                         continue
#                 else:
#                     try:
#                         vnamemin = styledata.nameaxis.convert((point[styledata.nameindex], styledata.selectindex, 0))
#                     except:
#                         continue
#                     try:
#                         vnamemax = styledata.nameaxis.convert((point[styledata.nameindex], styledata.selectindex, 1))
#                     except:
#                         continue
# 
#                 if styledata.valuepos:
#                     p = graph.vgeodesic(vnamemin, vvaluemin, vnamemin, vvaluemax)
#                     p.append(graph.vgeodesic_el(vnamemin, vvaluemax, vnamemax, vvaluemax))
#                     p.append(graph.vgeodesic_el(vnamemax, vvaluemax, vnamemax, vvaluemin))
#                     p.append(graph.vgeodesic_el(vnamemax, vvaluemin, vnamemin, vvaluemin))
#                     p.append(path.closepath())
#                 else:
#                     p = graph.vgeodesic(vvaluemin, vnamemin, vvaluemin, vnamemax)
#                     p.append(graph.vgeodesic_el(vvaluemin, vnamemax, vvaluemax, vnamemax))
#                     p.append(graph.vgeodesic_el(vvaluemax, vnamemax, vvaluemax, vnamemin))
#                     p.append(graph.vgeodesic_el(vvaluemax, vnamemin, vvaluemin, vnamemin))
#                     p.append(path.closepath())
#                 if barattrs is not None:
#                     graph.fill(p, barattrs)
# 
#     def key_pt(self, c, x_pt, y_pt, width_pt, height_pt, styledata):
#         l = len(styledata.valueindices)
#         if l > 1:
#             for i in range(l):
#                 c.fill(path.rect_pt(x_pt+i*width_pt/l, y_pt, width_pt/l, height_pt), attr.selectattrs(styledata.barattrs, i, l))
#         else:
#             c.fill(path.rect_pt(x_pt, y_pt, width_pt, height_pt), styledata.barattrs)
