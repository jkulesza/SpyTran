import pylab as plt
import numpy as np


def plot1DScalarFlux(fluxVec, meshX, enableYlog=False, fnameOut='fluxS', figNum=1, label='grpFlux'):
    plt.figure(figNum)
    plt.plot(meshX, fluxVec, linewidth='4', label=label)
    plt.ylabel("Flux (Arbitrary Scaling)")
    plt.xlabel("Position [cm]")
    if enableYlog:
        plt.yscale('log')
    plt.legend()
    plt.savefig(fnameOut)


def plot1DNeutronND(fluxVec, meshX, grp, enableYlog=False, fnameOut='nDn', figNum=2, energyVec=None):
    mN = 1.6749e-27  # mass of neutron [kg]
    eV2J = 1.60218e-19  # [J/eV]
    plt.figure(figNum)
    if not energyVec:
        # assume 10 energy grp structure by default
        energyVec = np.array([1e-3, 1e-2, 1e-1, 1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7])
    ndVec = fluxVec / np.sqrt((2 * eV2J * energyVec[::-1][grp]) / mN)
    plt.plot(meshX, ndVec, linewidth='4')
    plt.ylabel("Neutron Number Density (Arbitrary Scaling)")
    plt.xlabel("Position [cm]")
    if enableYlog:
        plt.yscale('log')
    plt.savefig(fnameOut)
