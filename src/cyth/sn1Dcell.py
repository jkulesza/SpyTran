import numpy as np
import scattSource as scs
# import scattSrc as scs
import scipy.special as spc
import sys
from utils.ordReader import gaussLegQuadSet
np.set_printoptions(linewidth=200)  # set print to screen opts


class Cell1DSn(object):
    """
    sN ordinates (sNords) dont have to be evenly distributed in mu-space.  can
    be specified to be biased to one particular direction, for instance, to
    represent a collumated beam more accurately.
    # define canned quadrature sets
    S2 Quadrature figure for example:

          (1) |  (2)
            \ | /
    mu=-1 ----------mu=1 (axis of sym)
    mu=cos(theta)
    in S2, bin by 90deg chunks
    """
    # STANDARD ORDINATES AND FLUX WEIGHTS FOR STD QUADRATURE SET
    sNwDict = {2: np.array([1.0, 1.0]),
               4: np.array([0.3478548451, 0.6521451549, 0.6521451549, 0.3478548451]),
               8: np.array([0.1012, 0.2224, 0.3137, 0.3627, 0.3627, 0.3137, 0.2224, 0.1012]),
               12: np.array([0.04717, 0.10693, 0.16007, 0.20316, 0.23349, 0.24914,
                            0.24914, 0.23349, 0.20316, 0.16007, 0.10693, 0.04717])
               }
    sNmuDict = {2: np.array([0.5773502691, -0.5773502691]),
                4: np.array([0.8611363115, 0.3399810435, -0.3399810435, -0.8611363115]),
                8: np.array([0.9603, 0.7967, 0.5255, 0.1834, -0.1834, -0.5255, -0.7967, -0.9603]),
                12: np.array([0.98156, 0.90411, 0.76990, 0.58731, 0.36783, 0.12523,
                              -0.12523, -0.36783, -0.58731, -0.76990, -0.90411, -0.98156])
                }

    def __init__(self, xpos, deltaX, nGroups=10, legOrder=8, sNords=2, **kwargs):
        quadSet = gaussLegQuadSet(sNords)
        self.faceNormals = np.array([-1, 1])
        self.centroid = xpos
        self.deltaX = deltaX
        self.sNords = sNords                                    # number of discrete dirs tracked
        self.sNmu, self.wN = quadSet[0], quadSet[1]             # quadrature weights
        self.maxLegOrder = legOrder                             # remember to range(maxLegORder + 1)
        self.legweights = np.zeros(legOrder + 1)
        self.nG = nGroups                                       # number of energy groups
        self.legArray = self._createLegArray(self.maxLegOrder)  # Stores leg polys
        #
        # initial flux guess
        iguess = kwargs.pop('iFlux', np.ones((nGroups, 3, self.sNords)))
        #
        # Ord flux vector: 0 is cell centered, 1 is left, 2 is right face
        self.ordFlux = iguess
        self.totOrdFlux = iguess
        #
        # Scattering Source term(s)
        self.qin = np.ones((nGroups, 3, self.sNords))  # init scatter/fission source
        self.previousQin = np.ones((nGroups, 3, self.sNords))  # init scatter/fission source
        #
        # optional volumetric source (none by default, fission or user-set possible)
        self.S = kwargs.pop('source', np.zeros((nGroups, 3, self.sNords)))
        #
        # set bc, if any given
        bc = kwargs.pop('bc', None)  # none denotes interior cell
        if bc is not None:
            self.setBC(bc)
        self.multiplying = False
        if type(self.S) is str:
            if self.S == 'fission':
                self.multiplying = True
            else:
                self.S = np.zeros((nGroups, 3, self.sNords))
        elif self.S is None:
            self.S = np.zeros((nGroups, 3, self.sNords))
        elif type(self.S) is np.ndarray:
            if self.S.shape != (nGroups, 3, self.sNords):
                sys.exit("FATALITY: Invalid shape of source vector. Shape must be (nGrps, 3, sNords).")

    def setBC(self, bc):
        """
        Assign boundary condition instance to cell.
        """
        self.boundaryCond = Sn1Dbc(bc)

    def applyBC(self, depth):
        """
        Enforce the boundary condition in cell.  Compute/adjust the cell face
        fluxes according to the boundary condition.
        """
        if hasattr(self, 'boundaryCond'):
            self.boundaryCond.applyBC(self, depth)
            return True
        else:
            print("WARNING: You are trying to apply a boundary condition in an interior cell.")
            return False

    def resetTotOrdFlux(self):
        self.totOrdFlux = np.zeros((self.nG, 3, self.sNords))

    def resetOrdFlux(self):
        self.ordFlux = np.zeros((self.nG, 3, self.sNords))

    def sweepOrd(self, skernel, chiNuFission, keff=1.0, depth=0, overRlx=1.0):
        """
        Use the scattering source iteration to sweep through sN discrete balance
        equations, one for each sN ordinate direction.
        Perform scattering source iteration

        Scattering source iteration:
        m = 0:
            [Omega'.grad + sigma_t] * qflux^(m)_g = fixed_source + fission_src
        when m>0:
            [Omega'.grad + sigma_t] * qflux^(m)_g =
            sum(o, sigma_s(r, g->g', Omega.Omega')_g * qflux^(m-1)_o)
        m is the scattering souce iteration index
        o is the direction ordinate
        g is the group index

        As m-> inf.  fewer and fewer neutrons will be around to contribute to the
        mth scattering source.  qflux^(m) should tend to 0 at large m.

        :Parameters:
            - :param arg1: descrition
            - :type arg1: type
            - :return: return desctipt
            - :rtype: return type
        """
        if depth >= 1:
            if depth >= 2:
                for g in range(self.nG):
                    self.qin[g, 0, :] = overRlx * (scs.evalScatterSource(self, g, skernel) -
                                                   self.previousQin[g, 0, :]) + self.previousQin[g, 0, :]
                self.previousQin = self.qin
            else:
                for g in range(self.nG):
                    self.qin[g, 0, :] = scs.evalScatterSource(self, g, skernel)
                self.previousQin = self.qin
        elif self.multiplying and depth == 0:
            for g in range(self.nG):
                # compute gth group fission source
                self.qin[g, 0, :] = self._computeFissionSource(g, chiNuFission, keff)
            self.resetTotOrdFlux()
        elif not self.multiplying and depth == 0:
            self.qin = self.S
            self.resetTotOrdFlux()
        return self.qin

    def _computeFissionSource(self, g, chiNuFission, keff):
        """
        Compute the withen group fission source.
        chiNuFission[g] is a row vector corresponding to all g'
        """
        if self.multiplying:
            return (1 / keff / 4.0 / (self.sNords * self.wN)) * \
                np.sum(chiNuFission[g] * self._evalTotScalarFlux(g))
        else:
            # need fixed source from user input
            print("Fission source requested for Non multiplying medium.  FATALITY")
            sys.exit()

    #@profile
    def _evalScatterSource(self, g, skernel):
        """
        computes within group scattering sources:
            sigma_s(x, Omega.Omega')*flux_n(r, omega)
            where n is the group
        returns vector of scattered ordinate fluxes

        compute sum_l((2l+1) * P_l(mu) * sigma_l * flux_l)
        where l is the legendre order
        returns a vecotr of length = len(mu)  (number of ordinate dirs)
        Amazingly, legendre.legval function provides exactly this capability
        """
        def ggprimeInScatter(g, l):
            """
            Computes in-scattring into grp g reaction rate.
            """
            return np.sum(skernel[l, g, :] * self._evalVecLegFlux(l))
        weights = np.zeros(self.maxLegOrder + 1)
        for l in range(self.maxLegOrder + 1):
            weights[l] = (2 * l + 1) * ggprimeInScatter(g, l)
        return np.polynomial.legendre.legval(self.sNmu, weights)

    def _evalScalarFlux(self, g, pos=0):
        """
        group scalar flux evaluator
        scalar_flux_g = (1/2) * sum_n(w_n * flux_n)
        n is the ordinate iterate
        """
        scalarFlux = np.sum(self.wN * self.ordFlux[g, pos, :])
        return 0.5 * scalarFlux

    def sumOrdFlux(self):
        self.totOrdFlux += self.ordFlux

    def _evalTotScalarFlux(self, g, pos=0):
        """
        group scalar flux evaluator
        scalar_flux_g = (1/2) * sum_n(w_n * flux_n)
        n is the ordinate iterate
        """
        scalarFlux = np.sum(self.wN * self.totOrdFlux[g, pos, :])
        return 0.5 * scalarFlux

    def getTotScalarFlux(self, pos=0):
        scalarFlux = []
        for g in range(self.nG):
            scalarFlux.append(self._evalTotScalarFlux(g, pos))
        return np.array(scalarFlux)

    def getFluxRatio(self, pos=0):
        partialFlux, totOrdFlux = 0, 0
        for g in range(self.nG):
            partialFlux += self._evalScalarFlux(g)
            totOrdFlux += self._evalTotScalarFlux(g)
        return partialFlux / totOrdFlux

    def _evalLegFlux(self, g, l, pos=0):
        """
        group legendre group flux
        scalar_flux_lg = (1/2) * sum_n(w_n * P_l * flux_n)
        where l is the legendre order
        and n is the ordinate iterate
        """
        legweights = np.zeros(self.maxLegOrder + 1)
        legweights[l] = 1.0
        legsum = np.sum(np.polynomial.legendre.legval(self.sNmu, legweights) *
                        self.wN * self.ordFlux[g, pos, :])
        return 0.5 * legsum

    def _evalVecLegFlux(self, l, pos=0):
        """
        Vectorized version of legendre moment of flux routine (must faster)

        group legendre group flux
        scalar_flux_lg = (1/2) * sum_n(w_n * P_l * flux_n)
        where l is the legendre order
        and n is the ordinate iterate
        """
        legsum = np.sum(spc.eval_legendre(l, self.sNmu) *
                        self.wN * (self.ordFlux[:, pos, :]), axis=1)
        return 0.5 * legsum

    def _createLegArray(self, lMax):
        legArray = np.zeros((lMax + 1, len(self.sNmu)))
        for l in range(lMax + 1):
            legArray[l, :] = spc.eval_legendre(l, self.sNmu)
        return legArray


class Sn1Dbc(object):
    def __init__(self, bc):
        self.vacBC = bc.pop('vac', None)
        self.refBC = bc.pop('ref', None)
        self.fixBC = bc.pop('fix', None)
        self.fixNBC = bc.pop('fixN', None)
        self.whiteBC = bc.pop('white', None)

    def applyBC(self, cell, depth):
        if self.vacBC is not None:
            try:
                face = self.vacBC[0]
            except:
                face = self.vacBC
            self.applyVacBC(cell, face)
        elif self.refBC is not None:
            try:
                face = self.refBC[0]
            except:
                face = self.refBC
            self.applyRefBC(cell, face)
        elif self.fixBC is not None:
            try:
                if depth == 0:
                    self.applyFixedFluxBC(cell, self.fixBC[0], self.fixBC[1])
                else:
                    self.applyVacBC(cell, self.fixBC[0])
            except:
                sys.exit("Incorrect format for fixed boundary condition.")
        elif self.fixNBC is not None:
            try:
                if depth == 0:
                    self.applyFixedNormFluxBC(cell, self.fixNBC[0], self.fixNBC[1])
                else:
                    self.applyVacBC(cell, self.fixNBC[0])
            except:
                sys.exit("Incorrect format for fixed boundary condition.")
        else:
            pass

    def applyRefBC(self, cell, face):
        """
        reflects cell outgoing flux at boundary to incomming flux
        ex: flux_2 == flux_1
        look for equal magnitude but opposite sign when assigning direction
        pairs
        """
        # directionPairs = []
        faceDot = cell.sNmu * cell.faceNormals[face - 1]
        # when dot product is (-) direction is oposite of outward normal to face
        # when dot product is (+) direction is same dir as outward normal to face
        # "same direction as face" == "pointing out of domain" ONLY IF
        # BCs are applied at the START of the space-sweep!!! YUCK.  TODO:
        # Simplify BC assignment.  way to garly right now.
        # TODO: does not generalize to arbitary ordinate dirs.  If asymetric
        # Sn is performed we need another, better method for reflection...
        inDirs = np.where(faceDot < 0.)[0]
        #outDirs = np.where(faceDot > 0.)
        #uniqueOctantOrds = np.unique(np.abs(faceDot))
        #for uniqueOrd in uniqueOctantOrds:
        #    directionPairs.append(np.where(np.abs(faceDot) == uniqueOrd))
        for iDir in inDirs:
            # get negative mu in iDir
            negDir = -1 * cell.sNmu[iDir]
            outDir = np.where(negDir == cell.sNmu)
            cell.ordFlux[:, face, iDir] = cell.ordFlux[:, face, outDir[0][0]]

    def applyVacBC(self, cell, face):
        """
        Sets all incomming fluxes equal to 0
        """
        faceDot = cell.sNmu * cell.faceNormals[face - 1]
        inwardDirs = np.where(faceDot < 0)
        cell.ordFlux[:, face, inwardDirs] = 0.0

    def applyFixedFluxBC(self, cell, face, bc):
        """
        sets incomming flux to user specified val
        """
        cell.ordFlux[:, face, :] = bc

    def applyFixedNormFluxBC(self, cell, face, bc):
        """
        Sets incomming flux in direction normal to the inward cell face equal
        to user set value.  less flexible than applyFixedFluxBC, but far
        more convinient for uni-directional beam problems.
        """
        faceDot = cell.sNmu * cell.faceNormals[face - 1]
        inwardDirs = np.where(faceDot < 0)
        for g in range(cell.nG):
            for inD in inwardDirs:
                # multiply by cosines of ordinate angles
                # scale by user set magnitude bc[0]
                # factor of 2 is for reflection about x axis in 1D
                #cell.ordFlux[g, face, 0] = 2 * bc[0] * bc[1][g]
                cell.ordFlux[g, face, inD] = 0.5 * bc[0] * np.abs(cell.sNmu[inD]) * bc[1][g] / cell.wN[inD]

    def applyWhiteBC():
        """
        Similar to reflecting boundary, but reflected flux is distributed
        isotropically.
        """
        pass
