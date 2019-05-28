# -*- coding: utf-8 -*-

import os

import pytest
import numpy as np

from ephMPS.model import Phonon, Mol, MolList
from ephMPS.transport.autocorr import TransportAutoCorr
from ephMPS.utils import Quantity, CompressConfig
from ephMPS.transport.tests import cur_dir


@pytest.mark.parametrize(
    "insteps",
    (
        50,
        None,
    ),
)
def test_autocorr(insteps):
    ph = Phonon.simple_phonon(Quantity(1), Quantity(1), 2)
    mol = Mol(Quantity(0), [ph])
    mol_list = MolList([mol] * 5, Quantity(1), 3)
    temperature = Quantity(50000, 'K')
    compress_config = CompressConfig(threshold=1e-3)
    ac = TransportAutoCorr(mol_list, temperature, insteps, compress_config=compress_config)
    ac.evolve(0.2, 50)
    corr_real = ac.auto_corr.real
    exact_real = get_exact_autocorr(mol_list, temperature, ac.evolve_times_array).real
    # direct comparison may fail because of different sign
    atol = 5e-3
    assert np.allclose(corr_real, exact_real, atol=atol) or np.allclose(corr_real, -exact_real, atol=atol)


def get_exact_autocorr(mol_list, temperature, time_series):
    try:
        autocorr = _get_exact_autocorr(mol_list, temperature, time_series)
    except ImportError:
        autocorr = None
    fname = os.path.join(cur_dir, 'autocorr.npz')
    if autocorr is None:
        return np.load(fname)['autocorr']
    else:
        np.savez(fname, autocorr=autocorr)
        return autocorr


def _get_exact_autocorr(mol_list, temperature, time_series):
    from ephMPS.utils.qutip_utils import get_clist, get_blist, get_hamiltonian, get_qnidx
    import qutip

    nsites = len(mol_list)
    J = mol_list.j_constant.as_au()
    ph = mol_list[0].dmrg_phs[0]
    ph_levels = ph.n_phys_dim
    omega = ph.omega[0]
    g = - ph.coupling_constant
    clist = get_clist(nsites, ph_levels)
    blist = get_blist(nsites, ph_levels)

    qn_idx = get_qnidx(ph_levels, nsites)
    H = get_hamiltonian(nsites, J, omega, g, clist, blist).extract_states(qn_idx)
    init_state = (-temperature.to_beta() * H).expm().unit()

    terms = []
    for i in range(nsites - 1):
        terms.append(clist[i].dag() * clist[i + 1])
        terms.append(-clist[i] * clist[i + 1].dag())
    j_oper = sum(terms).extract_states(qn_idx)

    corr = qutip.correlation(H, init_state, [0], time_series, [], j_oper, j_oper)[0]
    return corr



