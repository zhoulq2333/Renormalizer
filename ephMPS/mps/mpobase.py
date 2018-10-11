from __future__ import absolute_import, print_function, unicode_literals

import copy
import logging

import numpy as np
import scipy

from ephMPS.model.ephtable import EphTable
from ephMPS.mps.elementop import construct_ph_op_dict, construct_e_op_dict, ph_op_matrix
from ephMPS.mps.matrix import MatrixOp, DensityMatrixOp
from ephMPS.mps.mp import MatrixProduct
from ephMPS.mps.mpsbase import MpsBase
from ephMPS.utils import constant
from ephMPS.utils.utils import roundrobin

logger = logging.getLogger(__name__)

# todo: separate real opearator and density matrix operator.
# Because the latter one has more properties than the first one

def base_convert(n, base):
    """
    convert 10 base number to any base number
    """
    result = ''
    while True:
        tup = divmod(n, base)
        result += str(tup[1])
        if tup[0] == 0:
            return result[::-1]
        else:
            n = tup[0]


def get_pos(lidx, ridx, base, nqb):
    lstring = np.array(list(map(int, base_convert(lidx, base).zfill(nqb))))
    rstring = np.array(list(map(int, base_convert(ridx, base).zfill(nqb))))
    pos = tuple(roundrobin(lstring, rstring))
    return pos


def get_mpo_dim_qn(mol_list, scheme, rep):
    nmols = len(mol_list)
    mpo_dim = []
    mpo_qn = []
    if scheme == 1:
        for imol, mol in enumerate(mol_list):
            mpo_dim.append((imol + 1) * 2)
            mpo_qn.append([0] + [1, -1] * imol + [0])
            for iph in range(mol.nphs):
                if imol != nmols - 1:
                    mpo_dim.append((imol + 1) * 2 + 3)
                    mpo_qn.append([0, 0] + [1, -1] * (imol + 1) + [0])
                else:
                    mpo_dim.append(3)
                    mpo_qn.append([0, 0, 0])
    elif scheme == 2:
        # 0,1,2,3,4,5      3 is the middle
        # dim is 1*4, 4*6, 6*8, 8*6, 6*4, 4*1
        # 0,1,2,3,4,5,6    3 is the middle
        # dim is 1*4, 4*6, 6*8, 8*8, 8*6, 6*4, 4*1
        mididx = nmols // 2

        def elecdim(_imol):
            if _imol <= mididx:
                dim = (_imol + 1) * 2
            else:
                dim = (nmols - _imol + 1) * 2
            return dim

        for imol, mol in enumerate(mol_list):
            ldim = elecdim(imol)
            rdim = elecdim(imol + 1)

            mpo_dim.append(ldim)
            mpo_qn.append([0] + [1, -1] * (ldim // 2 - 1) + [0])
            for iph in range(mol.nphs):
                if rep == "chain":
                    if iph == 0:
                        mpo_dim.append(rdim + 1)
                        mpo_qn.append([0, 0] + [1, -1] * (rdim // 2 - 1) + [0])
                    else:
                        # replace the initial a^+a to b^+ and b
                        mpo_dim.append(rdim + 2)
                        mpo_qn.append([0, 0, 0] + [1, -1] * (rdim // 2 - 1) + [0])
                else:
                    mpo_dim.append(rdim + 1)
                    mpo_qn.append([0, 0] + [1, -1] * (rdim // 2 - 1) + [0])
    elif scheme == 3:
        # electronic nearest neighbor hopping
        # the electronic dimension is
        # 1*4, 4*4, 4*4,...,4*1
        for imol, mol in enumerate(mol_list):
            mpo_dim.append(4)
            mpo_qn.append([0, 1, -1, 0])
            for iph in range(mol.nphs):
                if imol != nmols - 1:
                    mpo_dim.append(5)
                    mpo_qn.append([0, 0, 1, -1, 0])
                else:
                    mpo_dim.append(3)
                    mpo_qn.append([0, 0, 0])

    mpo_dim[0] = 1
    return mpo_dim, mpo_qn


def get_qb_mpo_dim_qn(mol_list, old_dim, old_qn, rep):
        # quasi boson MPO dim
        qbopera = []  # b+b^\dagger MPO in quasi boson representation
        new_dim = []
        new_qn = []
        impo = 0
        for imol, mol in enumerate(mol_list):
            qbopera.append({})
            new_dim.append(old_dim[impo])
            new_qn.append(old_qn[impo])
            impo += 1
            for iph, ph in enumerate(mol.phs):
                nqb = ph.nqboson
                if nqb != 1:
                    if rep == "chain":
                        b = MpoBase.quasi_boson("b", nqb, mol.phs[iph].qbtrunc, base=mol.phs[iph].base)
                        bdagger = MpoBase.quasi_boson("b^\dagger", nqb, mol.phs[iph].qbtrunc, base=mol.phs[iph].base)
                        bpbdagger = MpoBase.quasi_boson("b + b^\dagger", nqb, mol.phs[iph].qbtrunc, base=mol.phs[iph].base)
                        qbopera[imol]["b" + str(iph)] = b
                        qbopera[imol]["bdagger" + str(iph)] = bdagger
                        qbopera[imol]["bpbdagger" + str(iph)] = bpbdagger

                        if iph == 0:
                            if iph != mol.nphs - 1:
                                addmpodim = [b[i].shape[0] + bdagger[i].shape[0] + bpbdagger[i].shape[0] - 1 for i in
                                             range(nqb)]
                            else:
                                addmpodim = [bpbdagger[i].shape[0] - 1 for i in range(nqb)]
                            addmpodim[0] = 0
                        else:
                            addmpodim = [(b[i].shape[0] + bdagger[i].shape[0]) * 2 - 2 for i in range(nqb)]
                            addmpodim[0] = 0

                    else:
                        bpbdagger = MpoBase.quasi_boson("C1(b + b^\dagger) + C2(b + b^\dagger)^2", nqb, ph.qbtrunc,
                                                        base=ph.base, c1=ph.term10, c2=ph.term20)

                        qbopera[imol]["bpbdagger" + str(iph)] = bpbdagger
                        addmpodim = [i.shape[0] for i in bpbdagger]
                        addmpodim[0] = 0
                        # the first quasi boson MPO the row dim is as before, while
                        # the others the a_i^\dagger a_i should exist
                else:
                    addmpodim = [0]

                # new MPOdim
                new_dim += [i + old_dim[impo] for i in addmpodim]
                # new MPOQN
                for iqb in range(nqb):
                    new_qn.append(old_qn[impo][0:1] + [0] * addmpodim[iqb] + old_qn[impo][1:])
                impo += 1
        new_dim.append(1)
        new_qn[0] = [0]
        new_qn.append([0])
        # the boundary side of L/R side quantum number
        # MPOQN[:MPOQNidx] is L side
        # MPOQN[MPOQNidx+1:] is R side
        return qbopera, new_dim, new_qn


class MpoBase(MatrixProduct):
    @classmethod
    def quasi_boson(cls, opera, nqb, trunc, base=2, c1=1.0, c2=1.0):
        '''
        nqb : # of quasi boson sites
        opera : operator to be decomposed
                "b + b^\dagger"
        '''
        assert opera in ["b + b^\dagger", "b^\dagger b", "b", "b^\dagger",
                         "C1(b + b^\dagger) + C2(b + b^\dagger)^2"]

        # the structure is [bra_highest_bit, ket_highest_bit,..., bra_lowest_bit,
        # ket_lowest_bit]
        mat = np.zeros([base, ] * nqb * 2)

        if opera == "b + b^\dagger" or opera == "b^\dagger" or opera == "b":
            if opera == "b + b^\dagger" or opera == "b^\dagger":
                for i in range(1, base ** nqb):
                    # b^+
                    pos = get_pos(i, i - 1, base, nqb)
                    mat[pos] = np.sqrt(i)

            if opera == "b + b^\dagger" or opera == "b":
                for i in range(0, base ** nqb - 1):
                    # b
                    pos = get_pos(i, i + 1, base, nqb)
                    mat[pos] = np.sqrt(i + 1)

        elif opera == "C1(b + b^\dagger) + C2(b + b^\dagger)^2":
            # b^+
            for i in range(1, base ** nqb):
                pos = get_pos(i, i - 1, base, nqb)
                mat[pos] = c1 * np.sqrt(i)
            # b
            for i in range(0, base ** nqb - 1):
                pos = get_pos(i, i + 1, base, nqb)
                mat[pos] = c1 * np.sqrt(i + 1)
            # bb
            for i in range(0, base ** nqb - 2):
                pos = get_pos(i, i + 2, base, nqb)
                mat[pos] = c2 * np.sqrt(i + 2) * np.sqrt(i + 1)
            # b^\dagger b^\dagger
            for i in range(2, base ** nqb):
                pos = get_pos(i, i - 2, base, nqb)
                mat[pos] = c2 * np.sqrt(i) * np.sqrt(i - 1)
            # b^\dagger b + b b^\dagger
            for i in range(0, base ** nqb):
                pos = get_pos(i, i, base, nqb)
                mat[pos] = c2 * float(i * 2 + 1)

        elif opera == "b^\dagger b":
            # actually Identity operator can be constructed directly
            for i in range(0, base ** nqb):
                # I
                pos = get_pos(i, i, base, nqb)
                mat[pos] = float(i)

        # check the original mat
        # mat = np.moveaxis(mat,range(1,nqb*2,2),range(nqb,nqb*2))
        # print mat.reshape(base**nqb,base**nqb)

        # decompose canonicalise
        mpo = cls()
        mpo.threshold = trunc
        mat = mat.reshape(1, -1)
        for idx in range(nqb - 1):
            u, s, vt = scipy.linalg.svd(mat.reshape(mat.shape[0] * base ** 2, -1),
                                        full_matrices=False)
            u = u.reshape(mat.shape[0], base, base, -1)
            mpo.append(u)
            mat = np.einsum("i, ij -> ij", s, vt)

        mpo.append(mat.reshape(-1, base, base, 1))
        # print "original MPO shape:", [i.shape[0] for i in MPO] + [1]
        mpo.build_empty_qn()
        mpo.ephtable = EphTable.all_phonon(mpo.site_num)
        # compress
        mpo.canonicalise()
        mpo.compress()
        # print "trunc", trunc, "distance", mpslib.distance(MPO,MPOnew)
        # fidelity = mpslib.dot(mpslib.conj(MPOnew), MPO) / mpslib.dot(mpslib.conj(MPO), MPO)
        # print "compression fidelity:: ", fidelity
        # print "compressed MPO shape", [i.shape[0] for i in MPOnew] + [1]

        return mpo

    @classmethod
    def from_mps(cls, mps):
        mpo = cls()
        mpo.mtype = DensityMatrixOp
        for ms in mps:
            mo = np.zeros([ms.shape[0]] + [ms.shape[1]] * 2 + [ms.shape[2]])
            for iaxis in range(ms.shape[1]):
                mo[:, iaxis, iaxis, :] = ms[:, iaxis, :].copy()
            mpo.append(mo)
        mpo.mol_list = mps.mol_list
        mpo.qn = copy.deepcopy(mps.qn)
        mpo.qntot = mps.qntot
        mpo.qnidx = mps.qnidx
        mpo.threshold = mps.threshold
        return mpo

    @classmethod
    def exact_propagator(cls, mol_list, x, space="GS", shift=0.0):
        '''
        construct the GS space propagator e^{xH} exact MPO
        H=\sum_{in} \omega_{in} b^\dagger_{in} b_{in}
        fortunately, the H is local. so e^{xH} = e^{xh1}e^{xh2}...e^{xhn}
        the bond dimension is 1
        shift is the a constant for H+shift
        '''
        assert space in ["GS", "EX"]

        mpo = cls().to_complex()
        mpo.mol_list = mol_list

        for imol, mol in enumerate(mol_list):
            e_pbond = mol.pbond[0]
            mo = np.zeros([1, e_pbond, e_pbond, 1])
            for ibra in range(e_pbond):
                mo[0, ibra, ibra, 0] = 1.0
            mpo.append(mo)

            for iph, ph in enumerate(mol.phs):

                if space == "EX":
                    # for the EX space, with quasiboson algorithm, the b^\dagger + b
                    # operator is not local anymore.
                    assert ph.nqboson == 1
                    ph_pbond = ph.pbond[0]
                    # construct the matrix exponential by diagonalize the matrix first
                    phop = construct_ph_op_dict(ph_pbond)

                    h_mo = phop['b^\dagger b'] * ph.omega[0] \
                           + phop['(b^\dagger + b)^3'] * ph.term30 \
                           + phop['b^\dagger + b'] * (ph.term10 + ph.term11) \
                           + phop['(b^\dagger + b)^2'] * (ph.term20 + ph.term21) \
                           + phop['(b^\dagger + b)^3'] * (ph.term31 - ph.term30)

                    w, v = scipy.linalg.eigh(h_mo)
                    h_mo = np.diag(np.exp(x * w))
                    h_mo = v.dot(h_mo)
                    h_mo = h_mo.dot(v.T)

                    mo = np.zeros([1, ph_pbond, ph_pbond, 1], dtype=np.complex128)
                    mo[0, :, :, 0] = h_mo

                    mpo.append(mo)

                elif space == "GS":
                    anharmo = False
                    # for the ground state space, yet doesn't support 3rd force
                    # potential quasiboson algorithm
                    ph_pbond = ph.pbond[0]
                    for i in ph.force3rd:
                        anharmo = not np.allclose(ph.force3rd[i] * ph.dis[i] / ph.omega[i], 0.0)
                        if anharmo:
                            break
                    if not anharmo:
                        for iboson in range(ph.nqboson):
                            mo = np.zeros([1, ph_pbond, ph_pbond, 1], dtype=np.complex128)

                            for ibra in range(ph_pbond):
                                mo[0, ibra, ibra, 0] = np.exp(
                                    x * ph.omega[0] * float(ph.base) ** (ph.nqboson - iboson - 1) * float(ibra))

                            mpo.append(mo)
                    else:
                        assert ph.nqboson == 1
                        # construct the matrix exponential by diagonalize the matrix first
                        phop = construct_ph_op_dict(ph_pbond)
                        h_mo = phop['b^\dagger b'] * ph.omega[0] + phop['(b^\dagger + b)^3'] * ph.term30
                        w, v = scipy.linalg.eigh(h_mo)
                        h_mo = np.diag(np.exp(x * w))
                        h_mo = v.dot(h_mo)
                        h_mo = h_mo.dot(v.T)

                        mo = np.zeros([1, ph_pbond, ph_pbond, 1], dtype=np.complex128)
                        mo[0, :, :, 0] = h_mo

                        mpo.append(mo)

        # shift the H by plus a constant



        mpo.qn = [[0]] * (len(mpo) + 1)
        mpo.qnidx = len(mpo) - 1
        mpo.qntot = 0

        mpo = mpo.scale(np.exp(shift * x))

        return mpo

    @classmethod
    def approx_propagator(cls, mpo, dt, thresh=0):
        """
        e^-iHdt : approximate propagator MPO from Runge-Kutta methods
        """

        mps = MpsBase()
        mps.mol_list = mpo.mol_list
        mps.dim = [1] * (mpo.site_num + 1)
        mps.qn = [[0]] * (mpo.site_num + 1)
        mps.qnidx = mpo.site_num - 1
        mps.qntot = 0
        mps.threshold = thresh

        for impo in range(mpo.site_num):
            ms = np.ones([1, mpo[impo].shape[1], 1], dtype=np.complex128)
            mps.append(ms)
        approx_mpo_t0 = MpoBase.from_mps(mps)

        approx_mpo = approx_mpo_t0.evolve(mpo, dt)

        # print"approx propagator thresh:", thresh
        # if QNargs is not None:
        # print "approx propagator dim:", [mpo.shape[0] for mpo in approxMPO[0]]
        # else:
        # print "approx propagator dim:", [mpo.shape[0] for mpo in approxMPO]

        # chkIden = mpslib.mapply(mpslib.conj(approxMPO, QNargs=QNargs), approxMPO, QNargs=QNargs)
        # print "approx propagator Identity error", np.sqrt(mpslib.distance(chkIden, IMPO, QNargs=QNargs) / \
        #                                            mpslib.dot(IMPO, IMPO, QNargs=QNargs))

        return approx_mpo

    @classmethod
    def onsite(cls, mol_list, opera, dipole=False, mol_idx_set=None):
        assert opera in ["a", "a^\dagger", "a^\dagger a"]
        nmols = len(mol_list)
        if mol_idx_set is None:
            mol_idx_set = set(np.arange(nmols))
        mpo_dim = []
        for imol in range(nmols):
            mpo_dim.append(2)
            for ph in mol_list[imol].phs:
                for iboson in range(ph.nqboson):
                    if imol != nmols - 1:
                        mpo_dim.append(2)
                    else:
                        mpo_dim.append(1)

        mpo_dim[0] = 1
        mpo_dim.append(1)
        # print opera, "operator MPOdim", MPOdim

        mpo = cls()
        mpo.mol_list = mol_list
        impo = 0
        for imol in range(nmols):
            pbond = mol_list.pbond_list[impo]
            eop = construct_e_op_dict(pbond)
            mo = np.zeros([mpo_dim[impo], pbond, pbond, mpo_dim[impo + 1]])

            if imol in mol_idx_set:
                if dipole:
                    factor = mol_list[imol].dipole
                else:
                    factor = 1.0
            else:
                factor = 0.0

            mo[-1, :, :, 0] = factor * eop[opera]

            if imol != 0:
                mo[0, :, :, 0] = eop['Iden']
            if imol != nmols - 1:
                mo[-1, :, :, -1] = eop['Iden']
            mpo.append(mo)
            impo += 1

            for ph in mol_list[imol].phs:
                for iboson in range(ph.nqboson):
                    pbond = mol_list.pbond_list[impo]
                    mo = np.zeros([mpo_dim[impo], pbond, pbond, mpo_dim[impo + 1]])
                    for ibra in range(pbond):
                        for idiag in range(mpo_dim[impo]):
                            mo[idiag, ibra, ibra, idiag] = 1.0

                    mpo.append(mo)
                    impo += 1

        # quantum number part
        # len(MPO)-1 = len(MPOQN)-2, the L-most site is R-qn
        mpo.qnidx = len(mpo) - 1

        totnqboson = 0
        for ph in mol_list[-1].phs:
            totnqboson += ph.nqboson

        if opera == "a":
            mpo.qn = [[0]] + [[-1, 0]] * (len(mpo) - totnqboson - 1) + [[-1]] * (totnqboson + 1)
            mpo.qntot = -1
        elif opera == "a^\dagger":
            mpo.qn = [[0]] + [[1, 0]] * (len(mpo) - totnqboson - 1) + [[1]] * (totnqboson + 1)
            mpo.qntot = 1
        elif opera == "a^\dagger a":
            mpo.qn = [[0]] + [[0, 0]] * (len(mpo) - totnqboson - 1) + [[0]] * (totnqboson + 1)
            mpo.qntot = 0
        mpo.qn[-1] = [0]

        return mpo

    @classmethod
    def ph_occupation_mpo(cls, mol_list, mol_idx, ph_idx=0):
        mpo = cls()
        mpo.mol_list = mol_list
        for imol, mol in enumerate(mol_list):
            e_pbond = mol.pbond[0]
            eop = construct_e_op_dict(e_pbond)
            mpo.append(eop['Iden'].reshape(1, e_pbond, e_pbond, 1))
            iph = 0
            for ph in mol.phs:
                for iqph in range(ph.nqboson):
                    ph_pbond = ph.pbond[iqph]
                    if imol == mol_idx and iph == ph_idx:
                        mt = ph_op_matrix('b^\dagger b', ph_pbond)
                    else:
                        mt = ph_op_matrix('Iden', ph_pbond)
                    mpo.append(mt.reshape(1, ph_pbond, ph_pbond, 1))
                    iph += 1
        mpo.build_empty_qn()
        return mpo

    @classmethod
    def max_entangled_ex(cls, mol_list, normalize=True):
        '''
        T = \infty maximum entangled EX state
        '''
        mps = MpsBase.gs(mol_list, max_entangled=True)
        # the creation operator \sum_i a^\dagger_i
        ex_mps = MpoBase.onsite(mol_list, "a^\dagger").apply(mps)
        if normalize:
            ex_mps.scale(1.0 / np.sqrt(float(len(mol_list))), inplace=True)  # normalize
        return cls.from_mps(ex_mps)

    def __init__(self, mol_list=None, j_matrix=None, scheme=2, rep="star", elocal_offset=None):
        '''
        scheme 1: l to r
        scheme 2: l,r to middle, the bond dimension is smaller than scheme 1
        scheme 3: l to r, nearest neighbour exciton interaction
        rep (representation) has "star" or "chain"
        please see doc
        '''
        assert rep in ["star", "chain"]

        super(MpoBase, self).__init__()
        self.mtype = MatrixOp
        if mol_list is None or j_matrix is None:
            return

        self.mol_list = mol_list
        nmols = len(mol_list)

        # used in the hybrid TDDMRG/TDH algorithm
        if elocal_offset is not None:
            assert len(elocal_offset) == nmols

        mpo_dim, mpo_qn = get_mpo_dim_qn(mol_list, scheme, rep)

        qbopera, mpo_dim, self.qn = get_qb_mpo_dim_qn(mol_list, mpo_dim, mpo_qn, rep)

        self.qnidx = len(self.qn) - 2
        self.qntot = 0  # the total quantum number of each bond, for Hamiltonian it's 0

        # print "MPOdim", MPOdim

        # MPO
        impo = 0
        for imol, mol in enumerate(mol_list):

            mididx = nmols // 2

            # electronic part
            pbond = mol_list.pbond_list[impo]
            mo = np.zeros([mpo_dim[impo], pbond, pbond, mpo_dim[impo + 1]])
            eop = construct_e_op_dict(pbond)
            # last row operator
            elocal = mol.elocalex
            if elocal_offset is not None:
                elocal += elocal_offset[imol]
            mo[-1, :, :, 0] = eop['a^\dagger a'] * (elocal + mol.e0)
            mo[-1, :, :, -1] = eop['Iden']
            mo[-1, :, :, 1] = eop['a^\dagger a']

            # first column operator
            if imol != 0:
                mo[0, :, :, 0] = eop['Iden']
                if (scheme == 1) or (scheme == 2 and imol <= mididx):
                    for ileft in range(1, mpo_dim[impo] - 1):
                        if ileft % 2 == 1:
                            mo[ileft, :, :, 0] = eop['a'] * j_matrix[(ileft - 1) // 2, imol]
                        else:
                            mo[ileft, :, :, 0] = eop['a^\dagger'] * j_matrix[(ileft - 1) // 2, imol]
                elif scheme == 2 and imol > mididx:
                    mo[-3, :, :, 0] = eop['a']
                    mo[-2, :, :, 0] = eop['a^\dagger']
                elif scheme == 3:
                    mo[-3, :, :, 0] = eop['a'] * j_matrix[imol - 1, imol]
                    mo[-2, :, :, 0] = eop['a^\dagger'] * j_matrix[imol - 1, imol]

            # last row operator
            if imol != nmols - 1:
                if (scheme == 1) or (scheme == 2 and imol < mididx) or (scheme == 3):
                    mo[-1, :, :, -2] = eop['a']
                    mo[-1, :, :, -3] = eop['a^\dagger']
                elif scheme == 2 and imol >= mididx:
                    for jmol in range(imol + 1, nmols):
                        mo[-1, :, :, (nmols - jmol) * 2] = eop['a^\dagger'] * j_matrix[imol, jmol]
                        mo[-1, :, :, (nmols - jmol) * 2 + 1] = eop['a'] * j_matrix[imol, jmol]

            # mat body
            if imol != nmols - 1 and imol != 0:
                if scheme == 1 or (scheme == 2 and imol < mididx):
                    for ileft in range(2, 2 * (imol + 1)):
                        mo[ileft - 1, :, :, ileft] = eop['Iden']
                elif scheme == 2 and imol > mididx:
                    for ileft in range(2, 2 * (nmols - imol)):
                        mo[ileft - 1, :, :, ileft] = eop['Iden']
                elif scheme == 2 and imol == mididx:
                    for jmol in range(imol + 1, nmols):
                        for ileft in range(imol):
                            mo[ileft * 2 + 1, :, :, (nmols - jmol) * 2] = eop['Iden'] * j_matrix[ileft, jmol]
                            mo[ileft * 2 + 2, :, :, (nmols - jmol) * 2 + 1] = eop['Iden'] * j_matrix[ileft, jmol]
            # scheme 3 no body mat

            self.append(mo)
            impo += 1

            # # of electronic operators retained in the phonon part, only used in
            # Mpo algorithm
            if rep == "chain":
                # except E and a^\dagger a
                nIe = mpo_dim[impo] - 2

            # phonon part
            for iph, ph in enumerate(mol.phs):
                nqb = mol.phs[iph].nqboson
                if nqb == 1:
                    pbond = mol_list.pbond_list[impo]
                    phop = construct_ph_op_dict(pbond)
                    mo = np.zeros([mpo_dim[impo], pbond, pbond, mpo_dim[impo + 1]])
                    # first column
                    mo[0, :, :, 0] = phop['Iden']
                    mo[-1, :, :, 0] = phop['b^\dagger b'] * ph.omega[0] + phop['(b^\dagger + b)^3'] * ph.term30
                    if rep == "chain" and iph != 0:
                        mo[1, :, :, 0] = phop['b'] * mol.phhop[iph, iph - 1]
                        mo[2, :, :, 0] = phop['b^\dagger'] * mol.phhop[iph, iph - 1]
                    else:
                        mo[1, :, :, 0] = phop['b^\dagger + b'] * (ph.term10 + ph.term11) \
                                         + phop['(b^\dagger + b)^2'] * (ph.term20 + ph.term21) \
                                         + phop['(b^\dagger + b)^3'] * (ph.term31 - ph.term30)
                    if imol != nmols - 1 or iph != mol.nphs - 1:
                        mo[-1, :, :, -1] = phop['Iden']
                        if rep == "chain":
                            if iph == 0:
                                mo[-1, :, :, 1] = phop['b^\dagger']
                                mo[-1, :, :, 2] = phop['b']
                                for icol in range(3, mpo_dim[impo + 1] - 1):
                                    mol[icol - 1, :, :, icol] = phop('Iden')
                            elif iph == mol.nphs - 1:
                                for icol in range(1, mpo_dim[impo + 1] - 1):
                                    mo[icol + 2, :, :, icol] = phop['Iden']
                            else:
                                mo[-1, :, : 1] = phop['b^\dagger']
                                mo[-1, :, :, 2] = phop['b']
                                for icol in range(3, mpo_dim[impo + 1] - 1):
                                    mo[icol, :, :, icol] = phop['Iden']
                        elif rep == "star":
                            if iph != mol.nphs - 1:
                                for icol in range(1, mpo_dim[impo + 1] - 1):
                                    mo[icol, :, :, icol] = phop['Iden']
                            else:
                                for icol in range(1, mpo_dim[impo + 1] - 1):
                                    mo[icol + 1, :, :, icol] = phop["Iden"]
                    self.append(mo)
                    impo += 1
                else:
                    # b + b^\dagger in Mpo representation
                    for iqb in range(nqb):
                        pbond = mol_list.pbond_list[impo]
                        phop = construct_ph_op_dict(pbond)
                        mo = np.zeros([mpo_dim[impo], pbond, pbond, mpo_dim[impo + 1]])

                        if rep == "star":
                            bpbdagger = qbopera[imol]["bpbdagger" + str(iph)][iqb]

                            mo[0, :, :, 0] = phop['Iden']
                            mo[-1, :, :, 0] = phop['b^\dagger b'] * mol.phs[iph].omega[0] * float(
                                mol.phs[iph].base) ** (nqb - iqb - 1)

                            #  the # of identity operator
                            if iqb != nqb - 1:
                                nI = mpo_dim[impo + 1] - bpbdagger.shape[-1] - 1
                            else:
                                nI = mpo_dim[impo + 1] - 1

                            for iset in range(1, nI + 1):
                                mo[-iset, :, :, -iset] = phop['Iden']

                            # b + b^\dagger 
                            if iqb != nqb - 1:
                                mo[1:bpbdagger.shape[0] + 1, :, :, 1:bpbdagger.shape[-1] + 1] = bpbdagger
                            else:
                                mo[1:bpbdagger.shape[0] + 1, :, :, 0:bpbdagger.shape[-1]] = bpbdagger

                        elif rep == "chain":

                            b = qbopera[imol]["b" + str(iph)][iqb]
                            bdagger = qbopera[imol]["bdagger" + str(iph)][iqb]
                            bpbdagger = qbopera[imol]["bpbdagger" + str(iph)][iqb]

                            mo[0, :, : 0] = phop['Iden']
                            mo[-1, :, :, 0] = phop['b^\dagger b'] * mol.phs[iph].omega[0] * float(
                                mol.phs[iph].base) ** (nqb - iqb - 1)

                            #  the # of identity operator
                            if impo == len(mpo_dim) - 2:
                                nI = nIe - 1
                            else:
                                nI = nIe

                            # print
                            # "nI", nI
                            for iset in range(1, nI + 1):
                                mo[-iset, :, :, -iset] = phop['Iden']

                            if iph == 0:
                                # b + b^\dagger 
                                if iqb != nqb - 1:
                                    mo[1:bpbdagger.shape[0] + 1, :, :, 1:bpbdagger.shape[-1] + 1] = bpbdagger
                                else:
                                    mo[1:bpbdagger.shape[0] + 1, :, :, 0:1] = bpbdagger * ph.term10
                            else:
                                # b^\dagger, b
                                if iqb != nqb - 1:
                                    mo[1:b.shape[0] + 1, :, :, 1:b.shape[-1] + 1] = b
                                    mo[b.shape[0] + 1:b.shape[0] + 1 + bdagger.shape[0], :, :, \
                                    b.shape[-1] + 1:b.shape[-1] + 1 + bdagger.shape[-1]] = bdagger
                                else:
                                    mo[1:b.shape[0] + 1, :, :, 0:1] = b * mol.phhop[iph, iph - 1]
                                    mo[b.shape[0] + 1:b.shape[0] + 1 + bdagger.shape[0], :, :, 0:1] \
                                        = bdagger * mol.phhop[iph, iph - 1]

                            if iph != mol.nphs - 1:
                                if iph == 0:
                                    loffset = bpbdagger.shape[0]
                                    roffset = bpbdagger.shape[-1]
                                else:
                                    loffset = b.shape[0] + bdagger.shape[0]
                                    roffset = b.shape[-1] + bdagger.shape[-1]
                                    # b^\dagger, b     
                                if iqb == 0:
                                    mo[-1:, :, :, roffset + 1:roffset + 1 + bdagger.shape[-1]] = bdagger
                                    mo[-1:, :, :,
                                    roffset + 1 + bdagger.shape[-1]:roffset + 1 + bdagger.shape[-1] + b.shape[-1]] = b
                                elif iqb == nqb - 1:
                                    # print
                                    # "He", loffset + 1, \
                                    # loffset + 1 + bdagger.shape[0], loffset + 1 + bdagger.shape[0] + b.shape[0],
                                    mo[loffset + 1:loffset + 1 + bdagger.shape[0], :, :, 1:2] = bdagger
                                    mo[loffset + 1 + bdagger.shape[0]:loffset + 1 + bdagger.shape[0] + b.shape[0], :, :,
                                    2:3] = b
                                else:
                                    mo[loffset + 1:loffset + 1 + bdagger.shape[0], :, :, \
                                    roffset + 1:roffset + 1 + bdagger.shape[-1]] = bdagger
                                    mo[loffset + 1 + bdagger.shape[0]:loffset + 1 + bdagger.shape[0] + b.shape[0], :, :,
                                    roffset + 1 + bdagger.shape[-1]:roffset + 1 + bdagger.shape[-1] + b.shape[-1]] = b

                        self.append(mo)
                        impo += 1

    @property
    def digest(self):
        return np.array([mt.var() for mt in self]).var()


    def promote_mt_type(self, mp):
        if self.mtype == DensityMatrixOp:
            mp.mtype = DensityMatrixOp
        if self.is_complex and not mp.is_complex:
            mp.to_complex(inplace=True)
        return mp

    def apply(self, mp):
        new_mps = self.promote_mt_type(mp.copy())
        if mp.is_mps:
            # mpo x mps
            for i, (mt_self, mt_other) in enumerate(zip(self, mp)):
                assert mt_self.shape[2] == mt_other.shape[1]
                # mt=np.einsum("apqb,cqd->acpbd",mpo[i],mps[i])
                mt = np.moveaxis(np.tensordot(mt_self, mt_other, axes=([2], [1])), 3, 1)
                mt = np.reshape(mt, [mt_self.shape[0] * mt_other.shape[0], mt_self.shape[1],
                                     mt_self.shape[-1] * mt_other.shape[-1]])
                new_mps[i] = mt
        elif mp.is_mpo:
            # mpo x mpo
            for i, (mt_self, mt_other) in enumerate(zip(self, mp)):
                assert mt_self.shape[2] == mt_other.shape[1]
                # mt=np.einsum("apqb,cqrd->acprbd",mt_s,mt_o)
                mt = np.moveaxis(np.tensordot(mt_self, mt_other, axes=([2], [1])), [-3, -2], [1, 3])
                mt = np.reshape(mt, [mt_self.shape[0] * mt_other.shape[0],
                                     mt_self.shape[1], mt_other.shape[2],
                                     mt_self.shape[-1] * mt_other.shape[-1]])
                new_mps[i] = mt
        else:
            assert False
        orig_idx = new_mps.qnidx
        new_mps.move_qnidx(self.qnidx)
        new_mps.qn = [np.add.outer(np.array(qn_o), np.array(qn_m)).ravel().tolist()
                      for qn_o, qn_m in zip(self.qn, new_mps.qn)]
        new_mps.move_qnidx(orig_idx)
        new_mps.qntot += self.qntot
        #new_mps.canonicalise()
        return new_mps

    def contract(self, mps):
        """
        a wrapper for apply. Include compress
        :param mps:
        :return:
        """
        if self.compress_method == 'svd':
            return self.contract_svd(mps)
        else:
            return self.contract_variational()

    def contract_svd(self, mps):

        """
        mapply->canonicalise->compress
        """
        new_mps = self.apply(mps)
        new_mps.canonicalise()
        new_mps.compress()
        return new_mps

    def contract_variational(self):
        raise NotImplementedError

    def conj_trans(self):
        new_mpo = self.copy()
        for i in range(new_mpo.site_num):
            new_mpo[i] = self[i].transpose(0, 2, 1, 3).conj()
        new_mpo.qn = [[-i for i in mt_qn] for mt_qn in new_mpo.qn]
        return new_mpo

    def thermal_prop(self, h_mpo, nsteps, temperature=298, approx_eiht=None, inplace=False):
        '''
        do imaginary propagation
        '''

        beta = constant.t2beta(temperature)
        # print "beta=", beta
        dbeta = beta / float(nsteps)

        ket_mpo = self if inplace else self.copy()

        if approx_eiht is not None:
            approx_eihpt = MpoBase.approx_propagator(h_mpo, -0.5j * dbeta, thresh=approx_eiht)
        else:
            approx_eihpt = None
        for istep in range(nsteps):
            logger.debug('Thermal propagating %d/%d' % (istep + 1, nsteps))
            ket_mpo = ket_mpo.evolve(h_mpo, -0.5j * dbeta, approx_eiht=approx_eihpt)
        return ket_mpo

    def get_reduced_density_matrix(self):
        assert self.mtype == DensityMatrixOp
        reduced_density_matrix_product = list()
        # ensure there is a first matrix in the new mps/mpo
        assert self.ephtable.is_electron(0)
        for idx, mt in enumerate(self):
            if self.ephtable.is_electron(idx):
                reduced_density_matrix_product.append(mt)
            else:  # phonon site
                reduced_mt = mt.trace(axis1=1, axis2=2)
                prev_mt = reduced_density_matrix_product[-1]
                new_mt = np.tensordot(prev_mt, reduced_mt, 1)
                reduced_density_matrix_product[-1] = new_mt
        reduced_density_matrix = np.zeros((self.mol_list.mol_num, self.mol_list.mol_num), dtype=np.complex128)
        for i in range(self.mol_list.mol_num):
            for j in range(self.mol_list.mol_num):
                elem = np.array([1]).reshape(1, 1)
                for mt_idx, mt in enumerate(reduced_density_matrix_product):
                    axis_idx1 = int(mt_idx == i)
                    axis_idx2 = int(mt_idx == j)
                    sub_mt = mt[:, axis_idx1, axis_idx2, :]
                    elem = np.tensordot(elem, sub_mt, 1)
                reduced_density_matrix[i][j] = elem.flatten()[0]
        return reduced_density_matrix

    def trace(self):
        assert self.mtype == DensityMatrixOp
        traced_product = []
        for mt in self:
            traced_product.append(mt.trace(axis1=1, axis2=2))
        ret = np.array([1]).reshape((1, 1))
        for mt in traced_product:
            ret = np.tensordot(ret, mt, 1)
        return ret.flatten()[0]