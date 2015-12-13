# to execute:
# From spytran dir:
#   python -m examples.1d_keigen
#

import spyTran as spytran
#import numpy as np
import os
pwdpath = os.path.dirname(os.path.realpath(__file__))

# Load xs database
import materials.materialMixxer as mx
mx.genMaterialDict('./materials/newXS')

# Solver settings
sN, nG = 4, 10

# Geometry
geoFile = pwdpath + '/geometry/2d_pin.geo'

# Materials
import utils.pinCellMatCalc as pcm
pinMaterial = pcm.createPinCellMat()
modMat = mx.mixedMat({'h1': 3.35e22 / 1e24, 'o16': 1.67e22 / 1e24})
modMat.setDensity(1.0)
materialDict = {'mat_1': pinMaterial,
                'mat_2': modMat,
                'mat_3': modMat}

# Boundary conditions
bcDict = {'bc1': 'vac',
          'bc2': 'vac',
          'bc3': 'vac',
          'bc4': 'vac'}

# Volumetric sources
srcDict = {'mat_1': 'fission',
           'mat_2': None}

# Init solver
slv = spytran.D1solver(geoFile, materialDict, bcDict, srcDict,
                       nG=nG, sN=sN, dim=2)

# Solve
slv.kSolve(residTol=1e-6, kTol=1e-5, outerIterMax=2)
slv.writeData(pwdpath + '/output/2Dpintest.h5')

# Plot
from fe.post import Fe2DOutput as fe2Dplt
plotter = fe2Dplt(pwdpath + '/output/2Dpintest.h5')
plotter.writeToVTK(fname=pwdpath + '/output/2Dpin')
