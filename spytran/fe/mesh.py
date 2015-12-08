import numpy as np
import scipy.sparse as sps
import scipy.sparse.linalg as spl
from d1.elements import d1InteriorElement
from d1.elements import d1BoundaryElement
from d2.elements import d2InteriorElement
from d2.elements import d2BoundaryElement
np.set_printoptions(linewidth=200)  # set print to screen opts


class SuperMesh(object):
    """
    Contains all region meshes.
    Contains mappings betwen array/matrix field representation and element class
    representation.
    """
    def __init__(self, gmshMesh, materialDict, bcDict, srcDict, nG, sNords, quadSet, dim=1):
        self.nG, self.sNords = nG, sNords
        self.sNmu, self.wN = quadSet[0], quadSet[1]
        self.nNodes = int(np.max(gmshMesh.regions.values()[0]['nodes'][:, 0] + 1))
        self.sysRHS = np.zeros((self.nG, self.sNords, self.nNodes))        # source vector
        self.scFluxField = np.zeros((self.nG, self.sNords, self.nNodes))   # scattered flux field
        self.totFluxField = np.zeros((self.nG, self.sNords, self.nNodes))  # total flux field
        fluxStor = (self.scFluxField, self.totFluxField)
        self.regions = {}     # mesh subregion dictionary
        for regionID, gmshRegion in gmshMesh.regions.iteritems():
            if gmshRegion['type'] == 'interior':
                self.regions[regionID] = RegionMesh(gmshRegion, fluxStor, materialDict[gmshRegion['material']],
                                                    bcDict, srcDict.get(gmshRegion['material'], None),
                                                    nGroups=self.nG, sNords=self.sNords, quadSet=quadSet, dim=dim)
            elif gmshRegion['type'] == 'bc':
                # mark boundary nodes
                pass
            else:
                print("Unknown region type sepecified in gmsh input. Ignoring")
        print("Number of nodes in mesh: " + str(self.nNodes))

    def scatter(self, depth, keff):
        for regionID, region in self.regions.iteritems():
            region.scatterSrc(depth, keff)

    def buildSysRHS(self):
        self.sysRHS = np.zeros((self.nG, self.sNords, self.nNodes))        # reset source vector
        for regionID, region in self.regions.iteritems():
            for g in range(self.nG):
                for o in range(self.sNords):
                    self.sysRHS = region.buildRegionRHS(self.sysRHS, g, o)

    def buildSysMatrix(self, depth):
        self.sysA = np.empty((self.nG, self.sNords), dtype=sps.dok.dok_matrix)
        self.sysP = np.empty((self.nG, self.sNords), dtype=object)
        for g in range(self.nG):
            for o in range(self.sNords):
                self.sysA[g, o] = self.constructA(g, o)
                if depth <= 1:
                    self.sysA[g, o] = sps.csc_matrix(self.sysA[g, o])
                    self.computePrecon(g, o)

    def computePrecon(self, g, o):
        #self.sysP[g, o] = spl.inv(self.sysA[g, o] * sps.eye(self.nNodes))
        M_x = lambda x: spl.spsolve(self.sysA[g, o] * sps.eye(self.nNodes), x)
        self.sysP[g, o] = spl.LinearOperator((self.nNodes, self.nNodes), M_x)

    def constructA(self, g, o):
        A = sps.dok_matrix((self.nNodes, self.nNodes))
        for regionID, region in self.regions.iteritems():
            A = region.buildRegionA(A, g, o)
        return A

    def sweepFlux(self, tolr):
        """
        For each angle and energy, solve a system of linear equations
        to update the flux scalar field on the mesh.
        """
        innerResid, Aresid = 0, 0
        for g in range(self.nG):
            for o in range(self.sNords):
                self.scFluxField[g, o], Aresid = \
                    spl.gmres(self.sysA[g, o], self.sysRHS[g, o], tol=tolr, M=self.sysP[g, o])
                #self.scFluxField[g, o] = \
                #    spl.spsolve(self.sysA[g, o], self.sysRHS[g, o])
                if Aresid > 0:
                    print("WARNING: Linear system solve failed.  Terminated at gmres iter: " + str(Aresid))
        self.totFluxField += self.scFluxField
        for regionID, region in self.regions.iteritems():
            fluxStor = (self.scFluxField, self.totFluxField)
            region.updateEleFluxes(fluxStor)
        return np.linalg.norm(self.scFluxField) / np.linalg.norm(self.totFluxField), innerResid

    def applyBCs(self, depth):
        for regionID, region in self.regions.iteritems():
            self.sysA, self.sysRHS = region.setBCs(self.sysA, self.sysRHS, depth)

    def initFlux(self, scFactor):
        fluxStor = (self.scFluxField, (0.0 * self.totFluxField + 1.0) * scFactor)
        for regionID, region in self.regions.iteritems():
            region.updateEleFluxes(fluxStor)

    def getFissionSrc(self):
        fissionSrc = 0
        for regionID, region in self.regions.iteritems():
            fissionSrc += region.getFissionSrc()
        return fissionSrc

    def resetMeshFlux(self):
        self.scFluxField = np.zeros((self.nG, self.sNords, self.nNodes))
        self.totFluxField = np.zeros((self.nG, self.sNords, self.nNodes))


class RegionMesh(object):
    def __init__(self, gmshRegion, fluxStor, material, bcDict, source, **kwargs):
        """
        Each region requires a material specification.

        Each region requires a node layout specification.
        A 1D mesh has the following structure:
        [[elementID1, x1, x2],
         [elementID2, x2, x3]
         ...
        ]
        """
        self.dim = kwargs.get("dim")
        self.nG = kwargs.get("nGroups")
        self.bcDict = bcDict
        self.totalXs = material.macroProp['Ntotal']
        self.skernel = material.macroProp['Nskernel']
        if 'chi' in material.macroProp.keys():
            self.nuFission = material.macroProp['Nnufission']
            self.chiNuFission = np.dot(np.array([material.macroProp['chi']]).T,
                                       np.array([material.macroProp['Nnufission']]))
            source = 'fission'
        else:
            self.nuFission = np.zeros(self.nG)
            self.chiNuFission = None
            #source = kwargs.pop("source", None)
        # Build elements in the region mesh
        self.buildElements(gmshRegion, fluxStor, source, **kwargs)
        self.linkBoundaryElements(gmshRegion)

    def buildElements(self, gmshRegion, fluxStor, source, **kwargs):
        """
        Initilize and store interior elements.
        """
        self.elements = {}
        for element in gmshRegion['elements']:
            nodeIDs = element[1:]
            nodePos = [gmshRegion['nodes'][nodeID][1] for nodeID in nodeIDs]
            if self.dim == 1:
                self.elements[element[0]] = d1InteriorElement((nodeIDs, nodePos), fluxStor, source, **kwargs)
            else:
                self.elements[element[0]] = d2InteriorElement((nodeIDs, nodePos), fluxStor, source, **kwargs)

    def linkBoundaryElements(self, gmshRegion):
        """
        Store boundary elements that border this region.  Link the interior element
        with its corrosponding boundary element
        """
        self.belements = {}  # boundary element dict (empty if subregion contains no boundaries)
        for bctype, bcElms in gmshRegion['bcElms'].iteritems():
            if type(bcElms) is dict:
                for bcElmID, nodeIDs in bcElms.iteritems():
                    nodePos = [gmshRegion['nodes'][nodeID][1] for nodeID in nodeIDs]
                    if self.dim == 1:
                        self.belements[bcElmID] = d1BoundaryElement(self.bcDict[bctype], (nodeIDs, nodePos), self.elements[bcElmID])
                    else:
                        self.belements[bcElmID] = d2BoundaryElement(self.bcDict[bctype], (nodeIDs, nodePos), self.elements[bcElmID])

    def buildRegionA(self, A, g, o):
        """
        Populate matrix A for group g for nodes in this region.
        This must only be done once
        as the system matrix A is not dependent on the flux.
        For each angle and energy the matrix A is only dependent on the
        total cross section (energy).
        Since A is very sparse, use scipy's sparse matrix class to save memory.
        """
        for elementID, element in self.elements.iteritems():
            nodeIDs, sysVals = element.getElemMatrix(g, o, self.totalXs)
            for nodeID, sysVal in zip(nodeIDs, sysVals):
                A[nodeID] += sysVal
        return A

    def buildRegionRHS(self, RHS, g, o):
        """
        Must be performed before each spatial flux solve.  RHS contains
        source terms and boundary values.  Source terms are dependent on the
        previous scattering iterations flux values.
        """
        for elementID, element in self.elements.iteritems():
            nodeIDs, RHSvals = element.getRHS(g, o)
            for nodeID, RHSval in zip(nodeIDs, RHSvals):
                #RHS[g, o, nodeID] = RHSval
                RHS[g, o, nodeID] += RHSval
        return RHS

    def setBCs(self, A, RHS, depth):
        A = self.setRegionBCsA(A, depth)
        RHS = self.setRegionBCsRHS(RHS, depth)
        return A, RHS

    def setRegionBCsA(self, A, depth):
        for belementID, belement in self.belements.iteritems():
            A = belement.applyBC2A(A, depth)
        return A

    def setRegionBCsRHS(self, RHS, depth):
        for belementID, belement in self.belements.iteritems():
            RHS = belement.applyBC2RHS(RHS, depth)
        return RHS

    def scatterSrc(self, depth, keff):
        """
        Perform scattering souce iteration for all elements in region.
        """
        for elementID, element in self.elements.iteritems():
            element.sweepOrd(self.skernel, self.chiNuFission, keff, depth)

    def updateEleFluxes(self, fluxStor):
        for elementID, element in self.elements.iteritems():
            element.updateFluxes(fluxStor)

    def getFissionSrc(self):
        fissionSrc = 0
        for elementID, element in self.elements.iteritems():
            for g in range(self.nG):
                fissionSrc += self.nuFission[g] * element.deltaX * element._evalCentTotAngleInt(g)
        #return np.dot(self.nuFission, self.getCellVols() * self.getTotScalarFlux().T)
        return fissionSrc

    #def getCellVols(self):
    #    for elementID, element in self.elements.iteritems():
    #    return cellVols
    #
    #def getTotScalarFlux(self):
    #    """ Produces an nGroup x nNodes ndarray """
    #    angleIntFlux = np.zeros((self.totFluxField.shape[0], self.totFluxField.shape[2]))
    #    for g in range(self.nG):
    #        for i in range(self.nNodes):
    #            angleIntFlux[g, i] = 0.5 * np.sum(self.wN * self.totFluxField)
    #    return angleIntFlux
