import unittest
import numpy as np
import sn1D as sn

# Load xs database
import materials.materialMixxer as mx
import utils.pinCellMatCalc as pcm
mx.genMaterialDict('./materials/hw2')
pinMaterial = pcm.createPinCellMat()

# plotters
import plotters.fluxEplot as flxPlt
import plotters.scalarFluxPlot as sfp


class test1DsnCell(unittest.TestCase):

    def testSetBCs(self):
        print("\n========= CHECKING BOUNDARY CONDITION ASSIGNMENT ==========")
        mesh1D = sn.Mesh1Dsn([0, 100], 1.0, pinMaterial, sN=4)
        bcs = {0: {'vac': (1, 0)}, -1: {'vac': (2, 0)}}
        mesh1D.setBCs(bcs)
        #
        # exterior cells
        self.assertEqual(mesh1D.cells[0].applyBC(0), True)
        self.assertEqual(mesh1D.cells[-1].applyBC(0), True)
        self.assertEqual(mesh1D.cells[0].ordFlux[:, 1, :].all(), 0.0)
        self.assertEqual(mesh1D.cells[0].ordFlux[:, 0, :].all(), 1.0)
        self.assertEqual(mesh1D.cells[0].ordFlux[:, 2, :].all(), 1.0)
        self.assertEqual(mesh1D.cells[-1].ordFlux[:, 2, :].all(), 0.0)
        self.assertEqual(mesh1D.cells[-1].ordFlux[:, 1, :].all(), 1.0)
        self.assertEqual(mesh1D.cells[-1].ordFlux[:, 0, :].all(), 1.0)
        #
        # should produce warning, no bc as this is an interior cell
        print("EXPECT WARNING:")
        self.assertEqual(mesh1D.cells[-2].applyBC(0), False)

    def testMeshSweep(self):
        print("\n========= INITIATING MESH SWEEP TEST ==========")
        mesh1D = sn.Mesh1Dsn([0, 10], 0.1, pinMaterial, sN=2)
        bcs = {0: {'vac': (1, 0)}, -1: {'vac': (2, 0)}}
        mesh1D.setBCs(bcs)
        #
        # Perform source iterations
        nSourceIterations = 1
        for si in range(nSourceIterations):
            mesh1D.sweepMesh(2)
        pass

    def testKeigenSweep(self):
        print("\n========= INITIATING K-EIGEN TEST ==========")
        width, dX = 1.0, 0.05
        mesh1D = sn.Mesh1Dsn([0, width], dX, pinMaterial, sN=8)
        # bcs = {0: {'vac': (1, 0)}, -1: {'vac': (2, 0)}}  # vac bc test
        bcs = {0: {'ref': (1, 0)}, -1: {'ref': (2, 0)}}   # ref bc test
        mesh1D.setBCs(bcs)
        #
        fissionSrc = []
        mesh1D.setKeff(1.)
        fissionSrc.append(np.sum(mesh1D.fissionSrc()))  # todo mult by width
        scalarFlux = mesh1D.getScalarFlux()
        sfp.plot1DScalarFlux(scalarFlux[:][:, 1], np.arange(0, width + dX, dX))
        for pI in range(8):
            # Perform source iterations
            nSourceIterations = 70
            for si in range(nSourceIterations):
                mesh1D.sweepMesh(10)
            fissionSrc.append(np.sum(mesh1D.fissionSrc()))
            knew = mesh1D.keff * (fissionSrc[-1] / fissionSrc[-2])
            print("Outter iteration: " + str(pI) + "  k-eff :" + str(knew))
            scalarFlux = mesh1D.getScalarFlux()
            flxPlt.plotFluxE(scalarFlux[len(np.arange(0, width + dX, dX)) / 2][::-1])
            sfp.plot1DScalarFlux(scalarFlux[:][:, 1], np.arange(0, width + dX, dX))
            mesh1D.setKeff(knew)
            mesh1D.postSI()


if __name__ == "__main__":
    unittest.main()
