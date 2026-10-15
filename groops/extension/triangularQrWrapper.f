c SPDX-License-Identifier: GPL-3.0-or-later
c ORBIT_POC_TRIANGULAR_QR_V31
c Merge an upper triangular factor with rectangular original-row blocks.
c The character arguments stay in Fortran, matching the native ABI policy.
      subroutine orbitpoctriangularqr(m,n,nb,a,lda,b,ldb,t,ldt,
     $                               z,y,work,info)
      implicit none
      integer m,n,nb,lda,ldb,ldt,info
      double precision a(lda,*),b(ldb,*),t(ldt,*)
      double precision z(*),y(*),work(*)
      external dtpqrt,dtpmqrt
      call dtpqrt(m,n,0,nb,a,lda,b,ldb,t,ldt,work,info)
      if(info.ne.0) return
      call dtpmqrt('L','T',m,1,n,0,nb,b,ldb,t,ldt,
     $             z,max(1,n),y,max(1,m),work,info)
      end
