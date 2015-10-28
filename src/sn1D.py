#!/usr/bin/python

# 1D specific Sn transport classes and methods
#
# Sweeps through energy, direction, and space on a 1D mesh
#
# To profile code:
# ----------------
# install line_profiler from pip:
# sudo pip install line_profiler
#
# Enable the profile decorators if desired on functions
# to profile:
#   @profile
#
# run the main script with:
#  kernprof -lv main.py
#

import numpy as np
import materials.materialMixxer as mx
import cyth.sn1Dcell as snc1d
from functools import partial
np.set_printoptions(linewidth=200)  # set print to screen opts
try:
    #from cyth.scattSrc import sweepOrd
    raise
except:
    print("WARNING: Cythonized scattering source code does not function.")
    print("WARNING: Fallback to pure python implementation.")
    from cyth.scattSource import sweepOrd


class Domain(object):
    """
    Top level class that holds all the problem specifications.  May be initilized
    from an input deck that is written in yml format that is translated into
    a dict and fed into the domain class to initilize the problem.
    """
    def __init__(self, inputDict):
        # specify sub-domain extents.  For serial implementation, one sub-domain
        # is sufficient as all mesh-material regions will belong to the same CPU
        self.subDomains
        self.dim = inputDict.pop("dim", 1)
        #
        # specify mesh-material region extents and materials
        # as key val pairs
        defaultMat = mx.mixedMat({'u235': 0.1, 'h1': 0.6, 'o16': 0.3})
        defaultMat.setDensity(1.0)
        self.matRegions.pop("matRegions", {'glob1': ([0, 10], 0.01, defaultMat)})
        #
        # specify sN order.  Provide pre-computed quadrature, allow user defined
        # quadrature sets as well.
        self.sNord = inputDict.pop("sNorder", 2)  # S2 by default
        #
        # specify material xsdir (xs folder), default to default mat dir
        self.xsdir = inputDict.pop("xsdir", "./materials/hw2")

    def solveTransport(self):
        # call inner sweeps on all subdomains.
        pass


class MultipyingDomain(Domain):
    def __init__(self, inputDict):
        super(Domain, self).__init__(inputDict)

    def solveKeigen(self):
        # perform power iteration using the latest flux estimate.
        pass


class SubDomain(object):
    """
    Inner iterations (i.e. sweeps through energy, angle, and space) are performed
    on each subdomain.  Boundary conditions are specified on each subdomain.

    In the case of multi-core: a special subdomain-subdomain boundary condition
    must be specified to pass information back and forth across subdomains after
    each inner iteration is performed
    """
    def __init__(self):
        self.regions = []    # contains mesh regions
        self.sweepTree = []  # constains (region, cell) tuples
        self.depth = 0
        self.keff = 1.0

    def addRegion(self, mesh1D):
        self.regions.append(mesh1D)

    def buildSweepTree(self):
        """
        After all regions are added, define mult region mesh list (sweepTree)
        that may be iterated over to sweep a multi region problem in the
        correct cell order.
        """
        minXPos, minXNodeID = self._findMinX()
        cellDistanceArray = self._computeDistance(minXPos, minXNodeID)  # distance of all cells to the "min X node"
        # sort distance array based on distances to min X cell
        cellDistanceArray = cellDistanceArray[cellDistanceArray[:, 2].argsort()]
        # cellDistanceArray = np.sort(cellDistanceArray, axis=2)
        for w, cellD in enumerate(cellDistanceArray):
            self.sweepTree.append((int(cellD[0]), int(cellD[1])))

    def getTotalCellsInDomain(self):
        totCells = 0
        for j, region in enumerate(self.regions):
            totCells += len(region.cells)
        return totCells

    def _computeDistance(self, minXPos, minXNodeID):
        distArray, w = np.zeros((self.getTotalCellsInDomain(), 3)), 0
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                distArray[w, :] = np.array([j, i, abs(minXPos - cell.centroid)])
                w += 1
        return distArray

    def _findMinX(self):
        minXPos = 1.e10
        # regions are indexed by j
        # within a region, cells are indexed by i
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                if cell.centroid < minXPos:
                    minXNodeID = (j, i)
                    minXPos = cell.centroid
                else:
                    pass
        return minXPos, minXNodeID

    def setKeff(self, k):
        for region in self.regions:
            region.keff = k
        self.keff = k

    def postSI(self):
        self.depth = 0

    def sweepSubDomain(self, stopI=2, overRlx=1.0):
        converged, i = False, 0
        for j, region in enumerate(self.regions):
            sweepOrdRed = partial(sweepOrd, skernel=region.skernel, chiNuFission=region.chiNuFission,
                                  keff=region.keff, depth=self.depth, overRlx=1.0)
            map(sweepOrdRed, region.cells)
            # #### DEPRECIATED ####
            #for i, cell in enumerate(region.cells):
                # compute the mth scattering source
            #    sweepOrd(cell, region.skernel, region.chiNuFission, self.keff, self.depth)
            # ### DEPRECIATED ####
        while not converged:
            # print("Source iteration: " + str(self.depth) + "  Space-angle sweep: " + str(i))
            self._sweepDir(1)
            self._sweepDir(2)
            i += 1
            if i >= stopI:
                # max number of space-angle sweeps to perform
                converged = True
        self.depth += 1     # increment scattering source iter
        return self._addOrdFlux()  # add mth scattered flux to the running total

    def _addOrdFlux(self):
        '''
        add Nth collided ord flux to running total
        '''
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                cell.sumOrdFlux()
        if self.depth >= 1. and np.mod(self.depth, 5) == 0:
            return self.computeResid()
        else:
            return 1.0

    def _sweepDir(self, f):
        """
        Step through space & angle

        f stands for face
        f is either 1 or 2 in 1D
        1 is left cell face,  2 is right face
        """
        lastCellFaceVal = np.zeros((self.regions[0].cells[0].nG,
                                    self.regions[0].cells[0].sNords))
        if f == 2:
            sweepTree = reversed(self.sweepTree)
        else:
            sweepTree = self.sweepTree
        blowoff = False
        for j, i in sweepTree:
            cell = self.regions[j].cells[i]
            if hasattr(cell, 'boundaryCond') and not blowoff:
                cell.applyBC(self.depth)
                blowoff = True
            else:
                # Interior cell
                cell.ordFlux[:, f, :] = lastCellFaceVal[:, :]
            # Only sweep through ordinates that have a component in same direction as
            # current sweep dir. Filter ords by dot product
            dotDir = cell.sNmu * cell.faceNormals[f - 1]
            ordsInSweepDir = np.where(dotDir < 0.)
            for o in np.arange(cell.sNords)[ordsInSweepDir]:
                cell.ordFlux[:, 0, o] = (cell.ordFlux[:, f, o] + self.regions[j].deltaX * cell.qin[:, 0, o] / (2. * np.abs(cell.sNmu[o]))) / \
                    (1. + self.regions[j].totalXs * self.regions[j].deltaX / (2. * np.abs(cell.sNmu[o])))
                if f == 1:
                    cell.ordFlux[:, 2, o] = 2. * cell.ordFlux[:, 0, o] - cell.ordFlux[:, f, o]
                    lastCellFaceVal[:, o] = cell.ordFlux[:, 2, o]
                elif f == 2:
                    cell.ordFlux[:, 1, o] = 2. * cell.ordFlux[:, 0, o] - cell.ordFlux[:, f, o]
                    lastCellFaceVal[:, o] = cell.ordFlux[:, 1, o]
            if np.any(cell.ordFlux[:, :, :] < 0.0):
                print("WARNING: Negative flux detected! Refine mesh in region #:" + str(j))
                maxStepSize = 2. * np.min(np.abs(cell.sNmu)) * min(1. / self.regions[j].totalXs)
                print("Max Step size in 1D: " + str(maxStepSize))
                # automatically gen refine factor: TODO: auto refine mesh
                refineFactor = self.regions[j].deltaX / maxStepSize
                raise Exception('coarse', refineFactor)

    def getOrdFlux(self):
        """
        getter for all groups and ordiante fluxes
        TODO: interate over sweep tree rather than over dummy lists
        """
        totOrdFlux = []
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                totOrdFlux.append(cell.totOrdFlux)
        return np.array(totOrdFlux)

    def fissionSrc(self):
        return np.dot(self.nuFission, self.getCellWidths() * self.getScalarFlux().T)

    def getScalarFlux(self):
        """
        getter for all scalar fluxes (angle integrated)
        TODO: interate over sweep tree rather than over dummy lists
        """
        totScalarFlux = []
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                totScalarFlux.append(cell.getTotScalarFlux())
        totScalarFlux = np.array(totScalarFlux)
        #return totScalarFlux / np.sum(totScalarFlux)  # norm flux to 1.
        return totScalarFlux

    def computeResid(self):
        residVec = []
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                residVec.append(cell.getFluxRatio())
        residVec = np.array(residVec)
        resid = np.max(residVec)
        print("Scattering Iteration: " + str(self.depth) +
              ".   Flux Residual= " + str("%.5e" % resid))
        return resid

    def getCellWidths(self):
        deltaXs = []
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                deltaXs.append(cell.deltaX)
        return np.array(deltaXs)

    def getCentroids(self):
        centroids = []
        for j, region in enumerate(self.regions):
            for i, cell in enumerate(region.cells):
                centroids.append(cell.centroid)
        return np.array(centroids)


class Mesh1Dsn(object):
    """
    Mesh region class.  Holds a single mesh with a designated material.
    Can be used in stand-alone mode where a single region problem may be
    setup and run only using this class.
    Provides methods to perform scattering and space-angle sweeps on the mesh.

    For multi-regoin problems see the subDomain class, which combines multiple
    mesh regions together.
    """
    def __init__(self, bounds, deltaX, material, **kwargs):
        sN = kwargs.pop("sN", 2)
        nGrps = kwargs.pop("gN", 10)
        legO = kwargs.pop("lN", 8)
        #vSource = kwargs.pop("source", None)
        self.keff = 1.0
        self.deltaX = deltaX
        self.depth = 0  # scattering source iteration
        #
        self.totalXs = material.macroProp['Ntotal']
        self.skernel = material.macroProp['Nskernel']
        if 'chi' in material.macroProp.keys():
            self.nuFission = material.macroProp['Nnufission']
            self.chiNuFission = np.dot(np.array([material.macroProp['chi']]).T,
                                       np.array([material.macroProp['Nnufission']]))
            src = 'fission'
        else:
            self.nuFission = None
            self.chiNuFission = None
            src = kwargs.pop("source", None)
        # initilize all cells in the mesh.
        self.cells = []
        for i, pos in enumerate(np.arange(bounds[0], bounds[1] + deltaX, deltaX)):
            #src = self.sourceExapnder(pos, src, vSource)
            self.cells.append(snc1d.Cell1DSn(pos, deltaX, nGrps, legO, sN, source=src))

    def sourceExapnder(self, x, src, vSource):
        if src == 'fission':
            return src
        elif hasattr(vSource, '__call__'):
            return vSource(x)
        elif type(vSource) is float:
            return vSource
        elif vSource is None:
            return None

    def setBCs(self, boundConds):
        """
        Where boundConds is a dict with cellID: boundaryCond pairs
        and boundCond is given as a str in ('vac', 'ref', 'white') or:
        in the special case of a fixed flux, a flux and direction cosine tuple.
        or a flux float and 'iso' str pair indicating an isotropic boundary source of
        strength give by the flux
        """
        for i, bc in boundConds.iteritems():
            self.cells[i].setBC(bc)

    #@profile
    def sweepMesh(self, stopI=2):
        """
        Outer space iterations:
            March through the cells in the mesh, update the ordinate fluxes as we go
            Specify ordinate direction to travel in.  Go in +mu dir, then back
            in the -mu direction (if necissary) untill convergence.

        Inner sN - energy iterations:
            perform scattering source inner iterations on each cell untill convergence.
            distribute neutrons in angle and energy.
        """
        # Sweep space
        converged, i = False, 0
        sweepOrdRed = partial(sweepOrd, skernel=self.skernel, chiNuFission=self.chiNuFission,
                              keff=self.keff, depth=self.depth, overRlx=1.0)
        map(sweepOrdRed, self.cells)
        # ### DEPRECIATED ####
        #for cell in self.cells:
            # compute the mth scattering source
        #    cell.sweepOrd(self.skernel, self.chiNuFission, self.keff, self.depth)
        # ### DEPRECIATED ####
        while not converged:
            # print("Source iteration: " + str(self.depth) + "  Space-angle sweep: " + str(i))
            self._sweepDir(1)
            self._sweepDir(2)
            i += 1
            if i >= stopI:
                # max number of space-angle sweeps to perform
                converged = True
        self.depth += 1     # increment scattering source iter
        return self._addOrdFlux()  # add mth scattered flux to the running total

    def _addOrdFlux(self):
        '''
        add Nth collided ord flux to running total
        '''
        for cell in self.cells:
            cell.sumOrdFlux()
        if self.depth >= 1. and np.mod(self.depth, 5) == 0:
            return self.computeResid()
        else:
            return 1.0

    def postSI(self):
        """
        Post Scatering Iteraions.
        In k-eigenvalue problems, after each outer power iteration, we have to
        reset the ordinate fluxes to zero.
        Also, reset the source iteration depth to 0.
        """
        # for cell in self.cells:
        #     cell.resetTotOrdFlux()
        self.depth = 0

    def _resetOrdFlux(self):
        for cell in self.cells:
            cell.resetOrdFlux()

    def getOrdFlux(self):
        """
        getter for all groups and ordiante fluxes
        """
        totOrdFlux = []
        for cell in self.cells:
            totOrdFlux.append(cell.totOrdFlux)
        return np.array(totOrdFlux)

    def fissionSrc(self):
        #fissionSrcVec = []
        #for cell in self.cells:
        #    fissionSrcVec.append(cell.fissionSrc[:, 0, :])
        #fissionSrcVec = np.array(fissionSrcVec)
        #return fissionSrcVec
        return np.dot(self.nuFission, self.getCellWidths() * self.getScalarFlux().T)

    def getScalarFlux(self):
        """
        getter for all scalar fluxes (angle integrated)
        """
        totScalarFlux = []
        for cell in self.cells:
            totScalarFlux.append(cell.getTotScalarFlux())
        totScalarFlux = np.array(totScalarFlux)
        #return totScalarFlux / np.sum(totScalarFlux)  # norm flux to 1.
        return totScalarFlux

    def computeResid(self):
        residVec = []
        for cell in self.cells:
            residVec.append(cell.getFluxRatio())
        residVec = np.array(residVec)
        resid = np.max(residVec)
        print("Scattering Iteration: " + str(self.depth) +
              ".   Flux Residual= " + str("%.5e" % resid))
        return resid

    def getCellWidths(self):
        deltaXs = []
        for cell in self.cells:
            deltaXs.append(cell.deltaX)
        return np.array(deltaXs)

    def getCentroids(self):
        centroids = []
        for cell in self.cells:
            centroids.append(cell.centroid)
        return np.array(centroids)

    def setKeff(self, k):
        self.keff = k

    def _sweepDir(self, f):
        """
        Step through space & angle

        f stands for face
        f is either 1 or 2 in 1D
        1 is left cell face,  2 is right face
        """
        lastCellFaceVal = np.zeros((self.cells[0].nG, self.cells[0].sNords))
        if f == 2:
            cellList = reversed(self.cells)
        else:
            cellList = self.cells
        blowoff = False
        for cell in cellList:
            if hasattr(cell, 'boundaryCond') and not blowoff:
                cell.applyBC(self.depth)
                blowoff = True
            else:
                # Interior cell
                cell.ordFlux[:, f, :] = lastCellFaceVal[:, :]
            # Only sweep through ordinates that have a component in same direction as
            # current sweep dir. Filter ords by dot product
            dotDir = cell.sNmu * cell.faceNormals[f - 1]
            ordsInSweepDir = np.where(dotDir < 0.)
            for o in np.arange(cell.sNords)[ordsInSweepDir]:
                cell.ordFlux[:, 0, o] = (cell.ordFlux[:, f, o] + self.deltaX * cell.qin[:, 0, o] / (2. * np.abs(cell.sNmu[o]))) / \
                    (1. + self.totalXs * self.deltaX / (2. * np.abs(cell.sNmu[o])))
                if f == 1:
                    cell.ordFlux[:, 2, o] = 2. * cell.ordFlux[:, 0, o] - cell.ordFlux[:, f, o]
                    lastCellFaceVal[:, o] = cell.ordFlux[:, 2, o]
                elif f == 2:
                    cell.ordFlux[:, 1, o] = 2. * cell.ordFlux[:, 0, o] - cell.ordFlux[:, f, o]
                    lastCellFaceVal[:, o] = cell.ordFlux[:, 1, o]
            if np.any(cell.ordFlux[:, :, :] < 0.0):
                print("WARNING: Negative flux detected! Refine mesh.")
                maxStepSize = 2. * np.min(np.abs(cell.sNmu)) * min(1. / self.totalXs)
                print("Max Step size in 1D: " + str(maxStepSize))
                refineFactor = 2.  # TODO: compute refinement factor on the fly
                raise Exception('coarse', refineFactor)
