# -*- coding: utf-8 -*-
# Author: Jiajun Ren <jiajunren0522@gmail.com>

'''
MPS/MPO structure ground state calculation solver
'''

import numpy as np
import scipy.linalg
import itertools
from pyscf import lib
from lib import mps as mpslib
from constant import *
from mpompsmat import *
from elementop import *
from lib import tensor as tensorlib

def construct_MPS_MPO_1():
    '''
    MPO/MPS structure 1
    e1,e2,e3...en,ph11,ph12,..ph21,ph22....phn1,phn2
    not implemented yet
    '''
    MPS = []
    MPO = []
    MPSdim = []
    MPOdim = []
    
    return MPS, MPO, MPSdim, MPOdim


def construct_MPS_MPO_2(mol, J, Mmax, nexciton, MPOscheme=2):
    '''
    MPO/MPS structure 2
    e1,ph11,ph12,..e2,ph21,ph22,...en,phn1,phn2...
    '''
    
    # e-ph table: e site 1, ph site 0
    ephtable = []
    # physical bond dimension
    pbond = []

    nmols = len(mol)
    for imol in xrange(nmols):
        ephtable.append(1)
        pbond.append(2)
        for iph in xrange(mol[imol].nphs):
            ephtable.append(0)
            pbond.append(mol[imol].ph[iph].nlevels)
    
    print "# of MPS,", len(pbond)
    print "physical bond,", pbond
    
    '''
    initialize MPS according to quantum number
    MPSQN: mps quantum number list
    MPSdim: mps dimension list
    MPS: mps list
    '''
    MPS, MPSdim, MPSQN = construct_MPS('L', ephtable, pbond, nexciton, Mmax, percent=1.0)
    print "initialize left-canonical:", mpslib.is_left_canonical(MPS)
    
    '''
    initialize MPO
    MPOdim: mpo dimension list
    MPO: mpo list
    '''
    MPO, MPOdim = construct_MPO(mol, J, pbond, scheme=MPOscheme)
    
    return MPS, MPSdim, MPSQN, MPO, MPOdim, ephtable, pbond


def construct_MPS(domain, ephtable, pbond, nexciton, Mmax, percent=0):
    '''
    construct 'domain' canonical MPS according to quantum number
    '''
    
    MPS = []
    MPSQN = [[0],]
    MPSdim = [1,]
 
    nmps = len(pbond)

    for imps in xrange(nmps-1):
        
        # quantum number 
        if ephtable[imps] == 1:
            # e site
            qnbig = list(itertools.chain.from_iterable([x, x+1] for x in MPSQN[imps]))
        else:
            # ph site 
            qnbig = list(itertools.chain.from_iterable([x]*pbond[imps] for x in MPSQN[imps]))
        
        Uset = []
        Sset = []
        qnset = []

        for iblock in xrange(min(qnbig),nexciton+1):
            # find the quantum number index
            indices = [i for i, x in enumerate(qnbig) if x == iblock]
            
            if len(indices) != 0 :
                a = np.random.random([len(indices),len(indices)])-0.5
                a = a + a.T
                S, U = scipy.linalg.eigh(a=a)
                Uset.append(blockrecover(indices, U, len(qnbig)))
                Sset.append(S)
                qnset +=  [iblock]*len(indices)

        Uset = np.concatenate(Uset,axis=1)
        Sset = np.concatenate(Sset)
        mps, mpsdim, mpsqn, nouse = updatemps(Uset, Sset, qnset, Uset, nexciton,\
                Mmax, percent=percent)
        # add the next mpsdim 
        MPSdim.append(mpsdim)
        MPS.append(mps.reshape(MPSdim[imps], pbond[imps], MPSdim[imps+1]))
        MPSQN.append(mpsqn)

    # the last site
    MPSQN.append([0])
    MPSdim.append(1)
    MPS.append(np.random.random([MPSdim[-2],pbond[-1],MPSdim[-1]])-0.5)
    
    print "MPSdim", MPSdim

    return MPS, MPSdim, MPSQN 


def blockrecover(indices, U, dim):
    '''
    recover the block element to its original position
    '''
    resortU = np.zeros([dim, U.shape[1]],dtype=U.dtype)
    for i in xrange(len(indices)):
        resortU[indices[i],:] = np.copy(U[i,:])

    return resortU


def updatemps(vset, sset, qnset, compset, nexciton, Mmax, percent=0):
    '''
    select basis to construct new mps, and complementary mps
    vset, compset is the column vector
    '''
    sidx = select_basis(qnset,sset,range(nexciton+1), Mmax, percent=percent)
    mpsdim = len(sidx)
    mps = np.zeros((vset.shape[0], mpsdim),dtype=vset.dtype)
    
    compmps = np.zeros((compset.shape[0],mpsdim), dtype=compset.dtype)

    mpsqn = []
    stot = 0.0
    for idim in xrange(mpsdim):
        mps[:, idim] = vset[:, sidx[idim]].copy()
        if sidx[idim] < compset.shape[1]:
            compmps[:,idim] = compset[:, sidx[idim]].copy() * sset[sidx[idim]]
        mpsqn.append(qnset[sidx[idim]])
        stot += sset[sidx[idim]]**2
    
    print "discard:", 1.0-stot

    return mps, mpsdim, mpsqn, compmps


def select_basis(qnset,Sset,qnlist,Mmax,percent=0):
    '''
    select basis according to Sset under qnlist requirement
    '''

    # convert to dict
    basdic = {}
    for i in xrange(len(qnset)):
        basdic[i] = [qnset[i],Sset[i]]
    
    # clean quantum number outside qnlist
    for ibas in basdic.iterkeys():
        if basdic[ibas][0] not in qnlist:
            del basdic[ibas]

    # each good quantum number block equally get percent/nblocks
    def block_select(basdic, qn, n):
        block_basdic = {i:basdic[i] for i in basdic if basdic[i][0]==qn}
        sort_block_basdic = sorted(block_basdic.items(), key=lambda x: x[1][1], reverse=True)
        nget = min(n, len(sort_block_basdic))
        print qn, "block # of retained basis", nget
        sidx = [i[0] for i in sort_block_basdic[0:nget]]
        for idx in sidx:
            del basdic[idx]

        return sidx

    nbasis = min(len(basdic), Mmax)
    print "# of selected basis", nbasis
    sidx = []
    
    # equally select from each quantum number block
    if percent != 0:
        nbas_block = int(nbasis * percent / len(qnlist))
        for iqn in qnlist:
            sidx += block_select(basdic, iqn, nbas_block)
    
    # others 
    nbasis = nbasis - len(sidx)
    
    sortbasdic = sorted(basdic.items(), key=lambda x: x[1][1], reverse=True)
    sidx += [i[0] for i in sortbasdic[0:nbasis]]

    assert len(sidx) == len(set(sidx))  # there must be no duplicated

    return sidx


def construct_MPO(mol, J, pbond, scheme=2):
    '''
    scheme 1: l to r
    scheme 2: l,r to middle, the bond dimension is smaller than scheme 1
    please see doc
    '''

    MPOdim = []
    MPO = []
    nmols = len(mol)
    
    # MPOdim  
    if scheme == 1:
        for imol in xrange(nmols):
            MPOdim.append((imol+1)*2)
            for iph in xrange(mol[imol].nphs):
                if imol != nmols-1:
                    MPOdim.append((imol+1)*2+3)
                else:
                    MPOdim.append(3)
    elif scheme == 2:
        # 0,1,2,3,4,5      3 is the middle 
        # dim is 1*4, 4*6, 6*8, 8*6, 6*4, 4*1 
        # 0,1,2,3,4,5,6    3 is the middle 
        # dim is 1*4, 4*6, 6*8, 8*8, 8*6, 6*4, 4*1 
        mididx = nmols/2

        def elecdim(imol):
            if imol <= mididx:
                dim = (imol+1)*2
            else:
                dim = (nmols-imol+1)*2
            return dim

        for imol in xrange(nmols):
            ldim = elecdim(imol)
            rdim = elecdim(imol+1)

            MPOdim.append(ldim)
        
            for iph in xrange(mol[imol].nphs):
                MPOdim.append(rdim+1)
        
    MPOdim[0]=1
    MPOdim.append(1)
    
    # MPO
    impo = 0
    for imol in xrange(nmols):
        # omega*coupling**2: a constant for single mol 
        e0 = 0.0
        for iph in xrange(mol[imol].nphs):
            e0 += mol[imol].ph[iph].omega * mol[imol].ph[iph].ephcoup**2
        
        mididx = nmols/2
        
        # electronic part
        mpo = np.zeros([MPOdim[impo],pbond[impo],pbond[impo],MPOdim[impo+1]])
        for ibra in xrange(pbond[impo]):
            for iket in xrange(pbond[impo]):
                # last row operator
                mpo[-1,ibra,iket,0]  = EElementOpera("a^\dagger a", ibra, iket) * (mol[imol].elocalex +  e0)
                mpo[-1,ibra,iket,-1] = EElementOpera("Iden", ibra, iket)
                mpo[-1,ibra,iket,1]  = EElementOpera("a^\dagger a", ibra, iket)
                
                # first column operator
                if imol != 0 :
                    mpo[0,ibra,iket,0] = EElementOpera("Iden", ibra, iket)
                    if (scheme==1) or (scheme==2 and imol<=mididx):
                        for ileft in xrange(1,MPOdim[impo]-1):
                            if ileft % 2 == 1:
                                mpo[ileft,ibra,iket,0] = EElementOpera("a", ibra, iket) * J[(ileft-1)/2,imol]
                            else:
                                mpo[ileft,ibra,iket,0] = EElementOpera("a^\dagger", ibra, iket) * J[(ileft-1)/2,imol]
                    elif scheme == 2 and imol > mididx:
                         mpo[-3,ibra,iket,0] = EElementOpera("a", ibra, iket) 
                         mpo[-2,ibra,iket,0] = EElementOpera("a^\dagger", ibra, iket)

                # last row operator
                if imol != nmols-1 :
                    if (scheme==1) or (scheme==2 and imol<mididx):
                        mpo[-1,ibra,iket,-2] = EElementOpera("a", ibra, iket)
                        mpo[-1,ibra,iket,-3] = EElementOpera("a^\dagger", ibra, iket)
                    elif scheme == 2 and imol >= mididx:
                        for jmol in xrange(imol+1,nmols):
                            mpo[-1,ibra,iket,(nmols-jmol)*2] = EElementOpera("a^\dagger", ibra, iket) * J[imol,jmol]
                            mpo[-1,ibra,iket,(nmols-jmol)*2+1] = EElementOpera("a", ibra, iket) * J[imol,jmol]

                # mat body
                if imol != nmols-1 and imol != 0:    
                    if (scheme==1) or (scheme==2 and (imol < mididx)):
                        for ileft in xrange(2,2*(imol+1)):
                            mpo[ileft-1,ibra,iket,ileft] = EElementOpera("Iden", ibra, iket)
                    elif (scheme==1) or (scheme==2 and (imol > mididx)):
                        for ileft in xrange(2,2*(nmols-imol)):
                            mpo[ileft-1,ibra,iket,ileft] = EElementOpera("Iden", ibra, iket)
                    elif (scheme==1) or (scheme==2 and imol==mididx):
                        for jmol in xrange(imol+1,nmols):
                            for ileft in xrange(imol):
                                mpo[ileft*2+1,ibra,iket,(nmols-jmol)*2] = EElementOpera("Iden", ibra, iket) * J[ileft,jmol]
                                mpo[ileft*2+2,ibra,iket,(nmols-jmol)*2+1] = EElementOpera("Iden", ibra, iket) * J[ileft,jmol]

        
        MPO.append(mpo)
        impo += 1
        
        # phonon part
        for iph in xrange(mol[imol].nphs):
            mpo = np.zeros([MPOdim[impo],pbond[impo],pbond[impo],MPOdim[impo+1]])
            for ibra in xrange(pbond[impo]):
                for iket in xrange(pbond[impo]):
                    # first column
                    mpo[0,ibra,iket,0] = PhElementOpera("Iden", ibra, iket)
                    mpo[1,ibra,iket,0] = PhElementOpera("b^\dagger + b",ibra, iket) * \
                                         mol[imol].ph[iph].omega * mol[imol].ph[iph].ephcoup
                    mpo[-1,ibra,iket,0] = PhElementOpera("b^\dagger b", ibra, iket) * mol[imol].ph[iph].omega
                    
                    if imol != nmols-1 or iph != mol[imol].nphs-1:
                        mpo[-1,ibra,iket,-1] = PhElementOpera("Iden", ibra, iket)
                        
                        if iph != mol[imol].nphs-1: 
                            for icol in xrange(1,MPOdim[impo+1]-1):
                                mpo[icol,ibra,iket,icol] = PhElementOpera("Iden", ibra, iket)
                        else:
                            for icol in xrange(1,MPOdim[impo+1]-1):
                                mpo[icol+1,ibra,iket,icol] = PhElementOpera("Iden", ibra, iket)

            MPO.append(mpo)
            impo += 1
    
    print "MPOdim", MPOdim
                    
    return  MPO, MPOdim 


def optimization(MPS, MPSdim, MPSQN, MPO, MPOdim, ephtable, pbond, nexciton, procedure, method="2site"):
    '''
    1 or 2 site optimization procedure
    '''
    
    assert method in ["2site", "1site"]
    print "optimization method", method
    
    # construct the environment matrix
    construct_enviro(MPS, MPS, MPO, "L")

    nMPS = len(MPS)
    # construct each sweep cycle scheme
    if method == "1site":
        loop = [['R',i] for i in xrange(nMPS-1,-1,-1)] + [['L',i] for i in xrange(0,nMPS)]
    else:
        loop = [['R',i] for i in xrange(nMPS-1,0,-1)] + [['L',i] for i in xrange(1,nMPS)]
    
    # initial matrix   
    ltensor = np.ones((1,1,1))
    rtensor = np.ones((1,1,1))
    
    energy = []
    for isweep in xrange(len(procedure)):
        print "Procedure", procedure[isweep]

        for system, imps in loop:
            if system == "R":
                lmethod, rmethod = "Enviro", "System"
            else:
                lmethod, rmethod = "System", "Enviro"
            
            if method == "1site":
                lsite = imps-1
                addlist = [imps]
            else:
                lsite= imps-2
                addlist = [imps-1, imps]
            
            ltensor = GetLR('L', lsite, MPS, MPS, MPO, itensor=ltensor, method=lmethod)
            rtensor = GetLR('R', imps+1, MPS, MPS, MPO, itensor=rtensor, method=rmethod)
            
            # get the quantum number pattern
            qnmat, qnbigl, qnbigr = construct_qnmat(MPSQN, ephtable,
                    pbond, addlist, method, system)
            cshape = qnmat.shape
            
            # hdiag
            tmp_ltensor = np.einsum("aba -> ba",ltensor)
            tmp_MPOimps = np.einsum("abbc -> abc",MPO[imps])
            tmp_rtensor = np.einsum("aba -> ba",rtensor)
            if method == "1site":
                #   S-a c f-S
                #   O-b-O-g-O
                #   S-a c f-S
                path = [([0, 1],"ba, bcg -> acg"),\
                        ([1, 0],"acg, gf -> acf")]
                hdiag = tensorlib.multi_tensor_contract(path, tmp_ltensor,
                        tmp_MPOimps, tmp_rtensor)[(qnmat==nexciton)]
                # initial guess   b-S-c 
                #                   a    
                cguess = MPS[imps][qnmat==nexciton]
            else:
                #   S-a c   d f-S
                #   O-b-O-e-O-g-O
                #   S-a c   d f-S
                tmp_MPOimpsm1 = np.einsum("abbc -> abc",MPO[imps-1])
                path = [([0, 1],"ba, bce -> ace"),\
                        ([0, 1],"edg, gf -> edf"),\
                        ([0, 1],"ace, edf -> acdf")]
                hdiag = tensorlib.multi_tensor_contract(path, tmp_ltensor,
                        tmp_MPOimpsm1, tmp_MPOimps, tmp_rtensor)[(qnmat==nexciton)]
                # initial guess b-S-c-S-e
                #                 a   d
                cguess = np.tensordot(MPS[imps-1], MPS[imps], axes=1)[qnmat==nexciton]

            nonzeros = np.sum(qnmat==nexciton)
            print "Hmat dim", nonzeros
            
            count = [0]
            def hop(c):
                # convert c to initial structure according to qn patter
                cstruct = c1d2cmat(cshape, c, qnmat, nexciton)
                count[0] += 1
                
                if method == "1site":
                    #S-a   l-S
                    #    d  
                    #O-b-O-f-O
                    #    e 
                    #S-c   k-S
                    
                    path = [([0, 1],"abc, adl -> bcdl"),\
                            ([2, 0],"bcdl, bdef -> clef"),\
                            ([1, 0],"clef, lfk -> cek")]
                    cout = tensorlib.multi_tensor_contract(path, ltensor,
                            cstruct, MPO[imps], rtensor)
                else:
                    #S-a       l-S
                    #    d   g 
                    #O-b-O-f-O-j-O
                    #    e   h
                    #S-c       k-S
                    path = [([0, 1],"abc, adgl -> bcdgl"),\
                            ([3, 0],"bcdgl, bdef -> cglef"),\
                            ([2, 0],"cglef, fghj -> clehj"),\
                            ([1, 0],"clehj, ljk -> cehk")]
                    cout = tensorlib.multi_tensor_contract(path, ltensor,
                            cstruct, MPO[imps-1], MPO[imps], rtensor)
                # convert structure c to 1d according to qn 
                return cout[qnmat==nexciton]

            precond = lambda x, e, *args: x/(hdiag-e+1e-4)
            e, c = lib.davidson(hop, cguess, precond, max_cycle=100) 
            # scipy arpack solver : much slower than davidson
            #A = scipy.sparse.linalg.LinearOperator((nonzeros,nonzeros), matvec=hop)
            #e, c = scipy.sparse.linalg.eigsh(A,k=1, which="SA",v0=cguess)
            print "HC loops:", count[0]

            print "isweep, imps, e=", isweep, imps, e
            energy.append(e)
            
            cstruct = c1d2cmat(cshape, c, qnmat, nexciton)

            # update the mps
            mps, mpsdim, mpsqn, compmps = Renormalization(cstruct, qnbigl, qnbigr,\
                    system, nexciton, procedure[isweep][0], percent=procedure[isweep][1])
            
            if method == "1site":
                MPS[imps] = mps
                if system == "L":
                    if imps != len(MPS)-1:
                        MPS[imps+1] = np.tensordot(compmps, MPS[imps+1], axes=1)
                        MPSdim[imps+1] = mpsdim
                        MPSQN[imps+1] = mpsqn
                    else:
                        MPS[imps] = np.tensordot(MPS[imps],compmps, axes=1)
                        MPSdim[imps+1] = 1
                        MPSQN[imps+1] = [0]

                else:
                    if imps != 0:
                        MPS[imps-1] = np.tensordot(MPS[imps-1],compmps, axes=1)
                        MPSdim[imps] = mpsdim
                        MPSQN[imps] = mpsqn
                    else:
                        MPS[imps] = np.tensordot(compmps, MPS[imps], axes=1)
                        MPSdim[imps] = 1
                        MPSQN[imps] = [0]
            else:
                if system == "L":
                    MPS[imps-1] = mps
                    MPS[imps] = compmps
                else:
                    MPS[imps] = mps
                    MPS[imps-1] = compmps

                MPSdim[imps] = mpsdim
                MPSQN[imps] = mpsqn

    lowestenergy = np.min(energy)
    print "lowest energy = ", lowestenergy

    return energy


def construct_qnmat(QN, ephtable, pbond, addlist, method, system):
    '''
    construct the quantum number pattern, the structure is as the coefficient
    QN: quantum number list at each bond
    ephtable : e-ph table 1 is electron and 0 is phonon 
    pbond : physical pbond
    addlist : the sigma orbital set
    '''
    print method
    assert method in ["1site","2site"]
    assert system in ["L","R"]
    qnl = np.array(QN[addlist[0]])
    qnr = np.array(QN[addlist[-1]+1])
    qnmat = qnl.copy()
    qnsigmalist = []

    for idx in addlist:

        if ephtable[idx] == 1:
            qnsigma = np.array([0,1])
        else:
            qnsigma = np.zeros([pbond[idx]],dtype=qnl.dtype)
        
        qnmat = np.add.outer(qnmat,qnsigma)
        qnsigmalist.append(qnsigma)

    qnmat = np.add.outer(qnmat,qnr)
    
    if method == "1site":
        if system == "R":
            qnbigl = qnl
            qnbigr = np.add.outer(qnsigmalist[-1],qnr)
        else:
            qnbigl = np.add.outer(qnl,qnsigmalist[0])
            qnbigr = qnr
    else:
        qnbigl = np.add.outer(qnl,qnsigmalist[0])
        qnbigr = np.add.outer(qnsigmalist[-1],qnr)

    return qnmat, qnbigl, qnbigr


def c1d2cmat(cshape, c, qnmat, nexciton):
    # recover good quantum number vector c to matrix format
    cstruct = np.zeros(cshape,dtype=c.dtype)
    np.place(cstruct, qnmat==nexciton, c)

    return cstruct


def Renormalization(cstruct, qnbigl, qnbigr, domain, nexciton, Mmax, percent=0):
    '''
        get the new mps, mpsdim, mpdqn, complementary mps to get the next guess
    '''
    assert domain in ["R", "L"]

    Uset, SUset, qnlnew, Vset, SVset, qnrnew = Csvd(cstruct, qnbigl, qnbigr, nexciton)
    if domain == "R":
        mps, mpsdim, mpsqn, compmps = updatemps(Vset, SVset, qnrnew, Uset, \
                nexciton, Mmax, percent=percent)
        return np.moveaxis(mps.reshape(list(qnbigr.shape)+[mpsdim]),-1,0), mpsdim, mpsqn,\
            compmps.reshape(list(qnbigl.shape) + [mpsdim])
    else:    
        mps, mpsdim, mpsqn, compmps = updatemps(Uset, SUset, qnlnew, Vset,\
                nexciton, Mmax, percent=percent)
        return mps.reshape(list(qnbigl.shape) + [mpsdim]), mpsdim, mpsqn,\
                np.moveaxis(compmps.reshape(list(qnbigr.shape)+[mpsdim]),-1,0)


def Csvd(cstruct, qnbigl, qnbigr, nexciton, full_matrices=True):
    '''
    block svd the coefficient matrix (l, sigmal, sigmar, r) or (l,sigma,r)
    according to the quantum number 
    '''
    Gamma = cstruct.reshape(np.prod(qnbigl.shape),np.prod(qnbigr.shape))
    localqnl = qnbigl.ravel()
    localqnr = qnbigr.ravel()
    
    Uset = []     # corresponse to nonzero svd value
    Uset0 = []    # corresponse to zero svd value
    Vset = []
    Vset0 = []
    Sset = []
    SUset0 = []
    SVset0 = []
    qnlset = []
    qnlset0 = []
    qnrset = []
    qnrset0 = []

    # different combination
    combine = [[x, nexciton-x] for x in xrange(nexciton+1)]
    for nl, nr in combine:
        lset = [i for i, x in enumerate(localqnl) if x == nl]
        rset = [i for i, x in enumerate(localqnr) if x == nr]
        if len(lset) != 0 and len(rset) != 0:
            Gamma_block = Gamma[np.ix_(lset, rset)]
            U, S, Vt = scipy.linalg.svd(Gamma_block)
            dim = S.shape[0]
            Sset.append(S)
            
            def blockappend(vset, vset0, qnset, qnset0, svset0, v, n, dim, indice, shape):
                vset.append(blockrecover(indice, v[:,:dim], shape))
                qnset += [n] * dim
                vset0.append(blockrecover(indice, v[:,dim:],shape))
                qnset0 += [n] * (v.shape[0]-dim)
                svset0.append(np.zeros(v.shape[0]-dim))
                
                return vset, vset0, qnset, qnset0, svset0
            
            Uset, Uset0, qnlset, qnlset0, SUset0 = blockappend(Uset, Uset0, qnlset, \
                    qnlset0, SUset0, U, nl, dim, lset, Gamma.shape[0])
            Vset, Vset0, qnrset, qnrset0, SVset0 = blockappend(Vset, Vset0, qnrset, \
                    qnrset0, SVset0, Vt.T, nr, dim, rset, Gamma.shape[1])
    
    if full_matrices == True:
        Uset = np.concatenate(Uset + Uset0,axis=1)
        Vset = np.concatenate(Vset + Vset0,axis=1)
        SUset = np.concatenate(Sset + SUset0)
        SVset = np.concatenate(Sset + SVset0)
        qnlset = qnlset + qnlset0
        qnrset = qnrset + qnrset0
        
        return Uset, SUset, qnlset, Vset, SVset, qnrset
    else:
        Uset = np.concatenate(Uset,axis=1)
        Vset = np.concatenate(Vset,axis=1)
        Sset = np.concatenate(Sset)
        
        return Uset, Sset, qnlset, Vset, Sset, qnrset


def clean_MPS(system, MPS, ephtable, nexciton):
    '''
    clean MPS (or finite temperature MPO) to good quantum number(nexciton) subseciton 
    if time step is too large the quantum number would not conserve due to numerical error
    '''

    assert system in ["L","R"]
    # if a MPO convert to MPSnew   
    if MPS[0].ndim == 4:
        MPSnew = mpslib.to_mps(MPS)
    elif MPS[0].ndim == 3:
        MPSnew = mpslib.add(MPS, None)

    nMPS = len(MPSnew)
    if system == 'L':
        start = 0
        end = nMPS
        step = 1
    else:
        start = nMPS-1
        end = -1
        step = -1
    
    MPSQN = [None] * (nMPS+1)
    MPSQN[0] = [0]
    MPSQN[-1] = [0]

    for imps in xrange(start, end, step):
        
        if system == "L":
            qn = np.array(MPSQN[imps])
        else:
            qn = np.array(MPSQN[imps+1])

        if ephtable[imps] == 1:
            # e site
            if MPS[0].ndim == 3:
                sigmaqn = np.array([0,1])
            else:
                sigmaqn = np.array([0,0,1,1])
        else:
            # ph site 
            sigmaqn = np.array([0]*MPSnew[imps].shape[1])
        
        if system == "L":
            qnmat = np.add.outer(qn,sigmaqn)
            Gamma = MPSnew[imps].reshape(-1, MPSnew[imps].shape[-1])
        else:
            qnmat = np.add.outer(sigmaqn,qn)
            Gamma = MPSnew[imps].reshape(MPSnew[imps].shape[0],-1)
        
        if imps != end-step:  # last site clean at last
            qnbig = qnmat.ravel()
            qnset = []
            Uset = []
            Vset = []
            Sset = []
            for iblock in xrange(nexciton+1):
                idxset = [i for i, x in enumerate(qnbig.tolist()) if x == iblock]
                if len(idxset) != 0:
                    if system == "L":
                        Gamma_block = Gamma[np.ix_(idxset,range(Gamma.shape[1]))]
                    else:
                        Gamma_block = Gamma[np.ix_(range(Gamma.shape[0]),idxset)]
                    try:
                        U, S, Vt = scipy.linalg.svd(Gamma_block,\
                                full_matrices=False, lapack_driver='gesdd')
                    except:
                        print "clean part gesdd converge failed"
                        U, S, Vt = scipy.linalg.svd(Gamma_block,\
                                full_matrices=False, lapack_driver='gesvd')

                    dim = S.shape[0]
                    Sset.append(S)
                    
                    def blockappend(vset, qnset, v, n, dim, indice, shape):
                        vset.append(blockrecover(indice, v[:,:dim], shape))
                        qnset += [n] * dim
                        
                        return vset, qnset

                    if system == "L":
                        Uset, qnset = blockappend(Uset, qnset, U, iblock, dim, idxset, Gamma.shape[0])
                        Vset.append(Vt.T)
                    else:
                        Vset, qnset = blockappend(Vset, qnset, Vt.T, iblock, dim, idxset, Gamma.shape[1])
                        Uset.append(U)
                    
            Uset = np.concatenate(Uset,axis=1)
            Vset = np.concatenate(Vset,axis=1)
            Sset = np.concatenate(Sset)
            
            if system == "L":
                MPSnew[imps] = Uset.reshape([MPSnew[imps].shape[0],MPSnew[imps].shape[1],len(Sset)])
                Vset =  np.einsum('ij,j -> ij', Vset, Sset)
                MPSnew[imps+1] = np.tensordot(Vset.T, MPSnew[imps+1], axes=1)
                MPSQN[imps+1] = qnset
            else:
                MPSnew[imps] = Vset.T.reshape([len(Sset),MPSnew[imps].shape[1],MPSnew[imps].shape[-1]])
                Uset =  np.einsum('ij,j -> ij', Uset, Sset)
                MPSnew[imps-1] = np.tensordot(MPSnew[imps-1], Uset, axes=1)
                MPSQN[imps] = qnset
        
        # clean the extreme mat
        else:
            if system == "L":
                qnmat = np.add.outer(qnmat,np.array([0]))
            else:
                qnmat = np.add.outer(np.array([0]), qnmat)
            cshape = MPSnew[imps].shape
            assert cshape == qnmat.shape
            c = MPSnew[imps][qnmat==nexciton]
            MPSnew[imps] = c1d2cmat(cshape, c, qnmat, nexciton)
            
    if MPS[0].ndim == 4:
        MPSnew = mpslib.from_mps(MPSnew)
    
    return MPSnew


