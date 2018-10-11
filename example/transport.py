# -*- coding: utf-8 -*-
# Author: Jiajun Ren <jiajunren0522@gmail.com>
#         Weitang Li <liwt31@163.com>
from __future__ import division

import os
import sys
import logging

import yaml

from ephMPS.model import Phonon, Mol, MolList
from ephMPS.mps import solver
from ephMPS.transport import ChargeTransport
from ephMPS.utils import log, Quantity

for env in ['MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'OMP_NUM_THREADS']:
    os.environ[env] = '1'

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('No or more than one parameter file are provided, abort')
        exit()
    parameter_path = sys.argv[1]
    with open(parameter_path) as fin:
        param = yaml.safe_load(fin)
    log.register_file_output(os.path.join(param['output dir'], param['fname'] + '.log'), 'w')
    ph_list = [Phonon.simple_phonon(Quantity(*omega), Quantity(*displacement), param['ph phys dim'])
               for omega, displacement in param['ph modes']]
    mol_list = MolList([Mol(Quantity(param['elocalex'], param['elocalex unit']), ph_list)] * param['mol num'])
    j_constant = Quantity(param['j constant'], param['j constant unit'])
    ct = ChargeTransport(mol_list, j_constant, temperature=Quantity(*param['temperature']))
    ct.stop_at_edge = True
    ct.economic_mode = True
    ct.memory_limit = 2 ** 30  # 1 GB
    #ct.memory_limit /= 10 # 100 MB
    ct.dump_dir = param['output dir']
    ct.job_name = param['fname']
    ct.custom_dump_info['comment'] = param['comment']
    ct.set_threshold(1e-4)
    evolve_dt = param['evolve dt']
    lowest_energy = solver.find_lowest_energy(ct.mpo, 1, 20)
    highest_energy = solver.find_highest_energy(ct.mpo, 1, 20)
    logger.debug('Energy of the Hamiltonian: {:g} ~ {:g}'.format(lowest_energy, highest_energy))
    if evolve_dt == 'auto':
        factor = min(highest_energy * 0.1 + (ct.initial_energy - lowest_energy) / (highest_energy - lowest_energy) * highest_energy * 1.8, highest_energy)
        evolve_dt = 1 / factor
        logger.info('Auto evolve delta t: {:g}'.format(evolve_dt))
        #evolve_dt = 1 / abs(highest_energy)
    ct.evolve(evolve_dt, param.get('nsteps'), param.get('evolve time'))