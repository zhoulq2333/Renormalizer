# -*- coding: utf-8 -*-
# Author: Jiajun Ren <jiajunren0522@gmail.com>

import copy
from functools import reduce

import numpy as np
import scipy

from ephMPS.mps.matrix import Matrix, MatrixState, MatrixOp, VirtualMatrixOp
from ephMPS.utils import svd_qn
from ephMPS.tdmps import rk


class MatrixProduct(list):

    def __init__(self, enable_qn=True):
        super(MatrixProduct, self).__init__()
        self.mtype = Matrix
        self._left_canon = None

        self.ephtable = None

        self.enable_qn = enable_qn
        self.qn = None
        self.qnidx = None
        self.qntot = None

        self.thresh = None


    def check_left_canonical(self):
        """
        check L-canonical
        """
        for mt in self[:-1]:
            if not mt.check_lortho():
                return False
        return True

    def check_right_canonical(self):
        """
        check R-canonical
        """
        for mt in self[1:]:
            if not mt.check_rortho():
                return False
        return True

    @property
    def site_num(self):
        return len(self)

    @property
    def is_left_canon(self):
        return self._left_canon
    
    @property
    def is_right_canon(self):
        return not self.is_left_canon

    @property
    def is_mps(self):
        return self.mtype == MatrixState

    @property
    def is_mpo(self):
        return self.mtype == MatrixOp or self.mtype == VirtualMatrixOp

    @property
    def iter_idx_list(self):
        if self.is_left_canon:
            return range(self.site_num - 1, 0, -1)
        else:
            return range(0, self.site_num - 1)

    @property
    def digest(self):
        if 10 < self.site_num:
            return None
        prod = np.eye(1).reshape(1, 1, 1)
        for ms in self:
            prod = np.tensordot(prod, ms, axes=1)
            prod = prod.reshape((prod.shape[0], -1, prod.shape[-1]))
        return {'var': prod.var(), 'mean': prod.mean(), 'ptp': prod.ptp()}

    def update_ms(self, idx, u, vt, sigma=None, qnlset=None, qnrset=None, m_trunc=None):
        if m_trunc is None:
            m_trunc = u.shape[1]
        u = u[:, :m_trunc]
        vt = vt[:m_trunc, :]
        if sigma is not None:
            sigma = sigma[:m_trunc]
            if self.is_left_canon:
                u = np.einsum('ji, i -> ji', u, sigma)
            else:
                vt = np.einsum('i, ij -> ij', sigma, vt)
        if self.is_left_canon:
            self[idx - 1] = np.tensordot(self[idx - 1], u, axes=1)
            ret_mpsi = np.reshape(vt, [m_trunc] + list(self[idx].pdim) + [vt.shape[1] / self[idx].pdim_prod])
            if qnrset is not None:
                self.qn[idx] = qnrset[:m_trunc]
        else:
            self[idx + 1] = np.tensordot(vt, self[idx + 1], axes=1)
            ret_mpsi = np.reshape(u, [u.shape[0] // self[idx].pdim_prod] + list(self[idx].pdim) + [m_trunc])
            if qnlset is not None:
                self.qn[idx + 1] = qnlset[:m_trunc]
        self[idx] = ret_mpsi
    
    def switch_domain(self):
        self._left_canon = not self._left_canon

    def get_big_qn(self, idx):
        mt = self[idx]
        if self.ephtable.is_electron(idx):
            # e site
            sigmaqn = mt.elec_sigmaqn
        else:
            # ph site
            sigmaqn = np.array([0] * mt.pdim_prod)
        qnl = np.array(self.qn[idx])
        qnr = np.array(self.qn[idx + 1])
        if self.is_left_canon:
            qnbigl = qnl
            qnbigr = np.add.outer(sigmaqn, qnr)
        else:
            qnbigl = np.add.outer(qnl, sigmaqn)
            qnbigr = qnr
        return qnbigl, qnbigr

    def calibrate_qnidx(self):
        if self.is_left_canon:
            self.move_qnidx(self.site_num - 1)
        else:
            self.move_qnidx(0)

    def norm(self):
        if self.is_left_canon:
            return np.linalg.norm(np.ravel(self[-1]))
        else:
            return np.linalg.norm(np.ravel(self[0]))

    def conj(self):
        """
        complex conjugate
        """
        new_mp = self.copy()
        for idx, mt in enumerate(new_mp):
            new_mp[idx] = mt.conj()
        return new_mp

    def add(self, other):
        assert self.qntot == other.qntot
        assert self.site_num == other.site_num
        new_mps = other.copy()

        if self.is_mps:  # MPS
            new_mps[0] = np.dstack([self[0], other[0]])
            for i in range(1, self.site_num - 1):
                mta = self[i]
                mtb = other[i]
                pdim = mta.shape[1]
                assert pdim == mtb.shape[1]
                new_mps[i] = np.zeros([mta.shape[0] + mtb.shape[0], pdim,
                                            mta.shape[2] + mtb.shape[2]], dtype=np.complex128)
                new_mps[i][:mta.shape[0], :, :mta.shape[2]] = mta[:, :, :]
                new_mps[i][mta.shape[0]:, :, mta.shape[2]:] = mtb[:, :, :]

            new_mps[-1] = np.vstack([self[-1], other[-1]])
        elif self.is_mpo:  # MPO
            new_mps[0] = np.concatenate((self[0], other[0]), axis=3)
            for i in range(1, self.site_num - 1):
                mta = self[i]
                mtb = other[i]
                pdimu = mta.shape[1]
                pdimd = mta.shape[2]
                assert pdimu == mtb.shape[1]
                assert pdimd == mtb.shape[2]

                new_mps[i] = np.zeros([mta.shape[0] + mtb.shape[0], pdimu, pdimd,
                                            mta.shape[3] + mtb.shape[3]], dtype=np.complex128)
                new_mps[i][:mta.shape[0], :, :, :mta.shape[3]] = mta[:, :, :, :]
                new_mps[i][mta.shape[0]:, :, :, mta.shape[3]:] = mtb[:, :, :, :]

                new_mps[-1] = np.concatenate((self[-1], other[-1]), axis=0)
        else:
            assert False

        if self.enable_qn and other.enable_qn:
            new_mps.move_qnidx(self.qnidx)
            new_mps.qn = [qn1 + qn2 for qn1, qn2 in zip(self.qn, new_mps.qn)]
            new_mps.qn[0] = [0]
            new_mps.qn[-1] = [0]
        return new_mps

    def dot(self, other):
        """
        dot product of two mps / mpo 
        """

        assert len(self) == len(other)
        e0 = np.eye(1, 1)
        for mt1, mt2 in zip(self, other):
            # sum_x e0[:,x].m[x,:,:]
            e0 = np.tensordot(e0, mt2, 1)
            # sum_ij e0[i,p,:] self[i,p,:]
            # note, need to flip a (:) index onto top,
            # therefore take transpose
            if mt1.ndim == 3:
                e0 = np.tensordot(e0, mt1, ([0, 1], [0, 1])).T
            if mt2.ndim == 4:
                e0 = np.tensordot(e0, mt1, ([0, 1, 2], [0, 1, 2])).T

        return e0[0, 0]

    def scale(self, val, inplace=False):

        if self.is_left_canon:
            ms_idx = -1
        else:
            ms_idx = 0

        # ms_idx = -1
        if inplace:
            self[ms_idx] *= val
        else:
            new_mp = self.copy()
            new_mp[ms_idx] *= val
            return new_mp

    def distance(self, other):
        return self.conj().dot(self) - self.conj().dot(other) - other.conj().dot(self) + other.conj().dot(other)

    def move_qnidx(self, dstidx):
        """
        Quantum number has a boundary side, left hand of the side is L system qn,
        right hand of the side is R system qn, the sum of quantum number of L system
        and R system is tot.
        """
        # construct the L system qn
        for idx in range(self.qnidx + 1, len(self.qn) - 1):
            self.qn[idx] = [self.qntot - i for i in self.qn[idx]]

        # set boundary to fsite:
        for idx in range(len(self.qn) - 2, dstidx, -1):
            self.qn[idx] = [self.qntot - i for i in self.qn[idx]]
        self.qnidx = dstidx

    def compress(self, check_canonical=False, normalize=None):
        """
        inp: canonicalise MPS (or MPO)

        trunc=0: just canonicalise
        0<trunc<1: sigma threshold
        trunc>1: number of renormalised vectors to keep

        side='l': compress LEFT-canonicalised MPS 
                  by sweeping from RIGHT to LEFT
                  output MPS is right canonicalised i.e. CRRR

        side='r': reverse of 'l'

        returns:
             truncated or canonicalised MPS
        """

        # if trunc==0, we are just doing a canonicalisation,
        # so skip check, otherwise, ensure mps is canonicalised
        if check_canonical:
            if self.is_left_canon:
                assert self.check_left_canonical()
            else:
                assert self.check_right_canonical()
        self.calibrate_qnidx()

        for idx in self.iter_idx_list:
            mt = self[idx]
            if self.is_left_canon:
                mt = mt.r_combine()
            else:
                mt = mt.l_combine()
            if self.enable_qn:
                qnbigl, qnbigr = self.get_big_qn(idx)
                u, sigma, qnlset, v, sigma, qnrset = svd_qn.Csvd(mt, qnbigl, qnbigr, self.qntot, full_matrices=False)
                vt = v.T
            else:
                qnlset = qnrset = None
                try:
                    u, sigma, vt = scipy.linalg.svd(mt, full_matrices=False, lapack_driver='gesdd')
                except:
                    # print "mps compress converge failed"
                    u, sigma, vt = scipy.linalg.svd(mt, full_matrices=False, lapack_driver='gesvd')

            if self.thresh < 1.:
                # count how many sing vals < trunc
                normed_sigma = sigma / scipy.linalg.norm(sigma)
                # m_trunc=len([s for s in normed_sigma if s >trunc])
                m_trunc = np.count_nonzero(normed_sigma > self.thresh)
            else:
                m_trunc = int(self.thresh)
                m_trunc = min(m_trunc, len(sigma))

            self.update_ms(idx, u, vt, sigma, qnlset, qnrset, m_trunc)

        self.switch_domain()

        if self.enable_qn:
            if self.is_left_canon:
                self.qnidx = len(self) - 1
            else:
                self.qnidx = 0
        if normalize is not None:
            self.scale(normalize / self.norm(), inplace=True)

    def canonicalise(self):
        self.calibrate_qnidx()
        for idx in self.iter_idx_list:
            mt = self[idx]
            if self.is_left_canon:
                mt = mt.r_combine()
            else:
                mt = mt.l_combine()
            if self.enable_qn:
                qnbigl, qnbigr = self.get_big_qn(idx)
                if self.is_left_canon:
                    system = "R"
                else:
                    system = "L"
                u, qnlset, v, qnrset = svd_qn.Csvd(mt, qnbigl, qnbigr, self.qntot,
                                                   QR=True, system=system, full_matrices=False)
                vt = v.T
            else:
                qnlset = qnrset = None
                if self.is_left_canon:
                    u, vt = scipy.linalg.rq(mt, mode='economic')
                else:
                    u, vt = scipy.linalg.qr(mt, mode='economic')
            self.update_ms(idx, u, vt, sigma=None, qnlset=qnlset, qnrset=qnrset)
        self.switch_domain()

        if self.enable_qn:
            if self.is_left_canon:
                self.qnidx = len(self) - 1
            else:
                self.qnidx = 0

    def evolve(self, mpo, evolve_dt, prop_method='C_RK4', compress_method='svd', approx_eiht=None):
        if approx_eiht:
            new_mps = approx_eiht.contract(self, compress_method=compress_method)
        else:
            propagation_c = rk.coefficient_dict[prop_method]
            termlist = [self]
            while len(termlist) < len(propagation_c):
                termlist.append(mpo.contract(termlist[-1], compress_method=compress_method))
            scaletermlist = []
            for idx, (mps_term, c_term) in enumerate(zip(termlist, propagation_c)):
                scaletermlist.append(mps_term.scale((-1.0j * evolve_dt) ** idx * c_term))
            new_mps = reduce(lambda mps1, mps2: mps1.add(mps2), scaletermlist)
            if new_mps.is_right_canon:
                new_mps.switch_domain()
            new_mps.canonicalise()
            new_mps.compress(normalize=1.0)
        return new_mps

    def copy(self):
        return copy.deepcopy(self)


    def __eq__(self, other):
        for m1, m2 in zip(self, other):
            if not np.allclose(m1, m2):
                return False
        return True

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return '%s with %d sites' % (self.__class__, len(self))

    def __setitem__(self, key, array):
        super(MatrixProduct, self).__setitem__(key, self.mtype(array))

    def append(self, array):
        super(MatrixProduct, self).append(self.mtype(array))