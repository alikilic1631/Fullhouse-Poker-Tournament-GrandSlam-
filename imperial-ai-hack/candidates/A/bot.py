"""Candidate A: Hyperion-faithful four-layer NLHE bot (stdlib only, single file).

  Layer 1  decision engine: fixed equity thresholds, never opponent specific.
  Layer 2  opponent model: Beta-prior statistics + 7-archetype posterior.
  Layer 3  exploit bridge: turns the model into range widths only (gated 20..60 actions).
  Layer 4  range-aware equity: preflop action -> base range -> postflop narrowing tiers
           -> exploit adjustment -> Monte Carlo (exact on the river) -> equity to layer 1.
"""
import base64
import gc
import math
import random
import time
import zlib
from bisect import bisect_left, bisect_right
from itertools import accumulate
from operator import mul

_pc = time.perf_counter

# ----------------------------------------------------------------------------- tables
RANKS = "23456789TJQKA"
SUITS = "cdhs"
CARD = {r + s: ri * 4 + si for ri, r in enumerate(RANKS) for si, s in enumerate(SUITS)}
# index 52 is a "no card" sentinel so turn rollouts can share the flop loop
RK = [5 ** (c >> 2) for c in range(52)] + [0]
SK = [8 ** (c & 3) for c in range(52)] + [0]
BIT = [1 << c for c in range(52)] + [0]
SBIT = [[(1 << (c >> 2)) if (c & 3) == s else 0 for c in range(52)] + [0] for s in range(4)]


def _straight_tbl():
    t = [-1] * 8192
    for m in range(8192):
        mm = (m << 1) | (1 if m & 4096 else 0)
        for top in range(13, 3, -1):
            if (mm >> (top - 4)) & 31 == 31:
                t[m] = top - 1
                break
    return t


STRT = _straight_tbl()


def _flush_tbl():
    t = [0] * 8192
    for m in range(8192):
        if bin(m).count("1") >= 5:
            sh = STRT[m]
            if sh >= 0:
                t[m] = (8 << 20) | (sh << 16)
            else:
                v = 5 << 20
                sft = 16
                for r in range(12, -1, -1):
                    if (m >> r) & 1:
                        v |= r << sft
                        sft -= 4
                        if sft < 0:
                            break
                t[m] = v
    return t


FLUSH = _flush_tbl()
FSUIT = [-1] * 4096      # suit holding >= 5 cards, from the packed 3-bit suit counters
FD4 = [0] * 4096         # 3 if some suit holds >= 4 cards (flush draw), else 0
for _k in range(4096):
    for _s in range(4):
        _n = (_k >> (3 * _s)) & 7
        if _n >= 5:
            FSUIT[_k] = _s
        if _n >= 4:
            FD4[_k] = 3


def _sdraw_tbl():
    t = [0] * 8192
    for m in range(8192):
        if STRT[m] >= 0:
            continue
        outs = 0
        for r in range(13):
            if not (m >> r) & 1 and STRT[m | (1 << r)] >= 0:
                outs += 1
        t[m] = 2 if outs >= 2 else outs
    return t


SDR = _sdraw_tbl()       # 0 none, 1 gutshot, 2 open-ended / double gutter


def _build_noflush():
    """Strength of every 5/6/7-card rank multiset, ignoring suits. key = sum(5**rank)."""
    T = {}
    cnt = [0] * 13
    ST = STRT

    def leaf(key):
        q = t0 = t1 = p0 = p1 = p2 = -1
        s = []
        mask = 0
        for r in range(12, -1, -1):
            n = cnt[r]
            if n:
                mask |= 1 << r
                if n == 1:
                    s.append(r)
                elif n == 2:
                    if p0 < 0:
                        p0 = r
                    elif p1 < 0:
                        p1 = r
                    elif p2 < 0:
                        p2 = r
                elif n == 3:
                    if t0 < 0:
                        t0 = r
                    elif t1 < 0:
                        t1 = r
                elif q < 0:
                    q = r
        if q >= 0:
            k = 0
            for r in range(12, -1, -1):
                if cnt[r] and r != q:
                    k = r
                    break
            v = (7 << 20) | (q << 16) | (k << 12)
        elif t0 >= 0 and (t1 >= 0 or p0 >= 0):
            v = (6 << 20) | (t0 << 16) | ((t1 if t1 >= 0 else p0) << 12)
        else:
            sh = ST[mask]
            if sh >= 0:
                v = (4 << 20) | (sh << 16)
            elif t0 >= 0:
                v = (3 << 20) | (t0 << 16) | (s[0] << 12) | (s[1] << 8)
            elif p1 >= 0:
                k = s[0] if s else -1
                if p2 > k:
                    k = p2
                v = (2 << 20) | (p0 << 16) | (p1 << 12) | (k << 8)
            elif p0 >= 0:
                v = (1 << 20) | (p0 << 16) | (s[0] << 12) | (s[1] << 8) | (s[2] << 4)
            else:
                v = (s[0] << 16) | (s[1] << 12) | (s[2] << 8) | (s[3] << 4) | s[4]
        T[key] = v

    def rec(r, used, key):
        if r == 13:
            if used >= 5:
                leaf(key)
            return
        pw = 5 ** r
        top = 7 - used
        if top > 4:
            top = 4
        for n in range(top + 1):
            cnt[r] = n
            rec(r + 1, used + n, key + n * pw)
        cnt[r] = 0

    rec(0, 0, 0)
    return T


NOFLUSH = _build_noflush()


def ev(cards):
    """Strength int of the best 5-card hand from 5-7 card ints (same order as the engine)."""
    k = 0
    s = 0
    for c in cards:
        k += RK[c]
        s += SK[c]
    f = FSUIT[s]
    if f < 0:
        return NOFLUSH[k]
    m = 0
    for c in cards:
        if c & 3 == f:
            m |= 1 << (c >> 2)
    return FLUSH[m]


# ----------------------------------------------------------------------------- combos
CA, CB, CCLS, CRK, CSK, CMASK, CRM = [], [], [], [], [], [], []
CSM = [[], [], [], []]


def _cls(c1, c2):
    i = 12 - (c1 >> 2)
    j = 12 - (c2 >> 2)
    if i == j:
        return i * 13 + j
    hi, lo = (i, j) if i < j else (j, i)
    return hi * 13 + lo if (c1 & 3) == (c2 & 3) else lo * 13 + hi


for _a in range(52):
    for _b in range(_a + 1, 52):
        CA.append(_a)
        CB.append(_b)
        CCLS.append(_cls(_a, _b))
        CRK.append(RK[_a] + RK[_b])
        CSK.append(SK[_a] + SK[_b])
        CMASK.append(BIT[_a] | BIT[_b])
        CRM.append((1 << (_a >> 2)) | (1 << (_b >> 2)))
        for _s in range(4):
            CSM[_s].append(SBIT[_s][_a] | SBIT[_s][_b])
ALLI = list(range(1326))

# ----------------------------------------------------------------------------- preflop data
_R13 = "AKQJT98765432"
PF_COMBOS = [6 if i == j else (4 if i < j else 12) for i in range(13) for j in range(13)]
_PF_BLOB = "c-j@Z=UW@;w&wk>&CEGx@9lOVgRxBpMI@mtkqss%WvNs-=b$QO2@#C#ZnxVJXSYN5jx%S6^S(3ld7jpF@u5Vi>Z$dtb>F{R@W;RW{P|B`|M=;{FQ5PNk5{jMeDVCv`^%RfKfn2(UoM}&c>3z?`<Jgiy!rFT_m@9Dd-e3)%TF)g{_W@2&whIN!}FIfUS3}Q^V83-o;-i}{nKY3E-(M}$FHy7K7IV);gc6H-u&N>Uq5}keE$6Whi9)o{OilN_a9!rdHML_hs($R{PpuMUp~Ei`||t8Kfd|r&wu*z?iX<8%a=dB{LjDq^7Y%dFQ49i`1I`6|M~M@zkU7rmoM+XeED|Ss#I&$x~c1pvyHw=y;`f(n&n!veRdXSX^~YFji!wU9e$4FDMSz@QfZuuSOCIML6>y1`9Kk|1so*>P7+Vg%CaDZVVn^Ot<|wiL!_1p1S89554Ezw5l93gB<B93iegG4i!8z<Te;8_P0@J{iIeQ<1HEdRB~|0a72)K*UM?F|U6pu!LoYWit68?x+Li8-h{6&{VH{3xpZ0-M>W!0fz12A7>p>i4BteoT{hU8zqZCccoGMGF>;=Y!iwrLbf_z5b7eyj~K@=}aC)`7o7lp-q5fjBz;YYAao`@DvgnlSLuu6g`3(HxGYDkYu4O5jcVhtsl+E1n=8>TF<cZm-7eMwbJ)f6~k*-%=oifUL!S9iWDpbSKagg{;=2UHlrDV{(`dcD)MS!KD@YBf(=XAIej&<rg~ibA(Z>An(!F`g87wWZQ+mWeS4$qMXgiFl~U+!Bi8iq@f&hZU3O?xMKBH8}oEGew49M@g(&BERPiK^C|OL!Yq1Mb*?5i=Z~RhGhIuGL4F=>7})D$xut8tla3&K^hNpB*l@~zd?ODh2;=}r)Z`Z&)g6Z2qS2cqPEVO^<JeeH`~qg&aom=%|(m?mDIGlE{H90nWSk(k}ABQpNUcw!4yU`Bv!gGSZ*0%c&cV_{Dr~`WIRuiHHp_wG#MPO3wVp?)E_FQ$jQtK-BKj}k*U>mxy&!iiYAJJa-~0=I4sje94AQTN^$ror6V*0rx>mWPW2~_ix>_z9Ph~&53Z|ZI*(#7yK#1MetL)3E7g-mr_M1FWz1nDMKVg0QaHSdg%Ok%g)&P~!Z9dSp~$dRffv~arl!r)G*uD_g?eD>m=dGFfyA;;bY2m~RbCY}n*H9iR8lsUa0<g{=IXVhWI9`cVFVG00c_|novC09S|G50N09DRs)QpLM+rCKLSZOjLO28yct4uSXL=PPM+r2ye*gYiy?I48+Gg`u6bKy0>q`U!37RZ&62Y~_AjSxa0UD7}PIxgwA)q5zN#r|%Oa%o_Re!71Pi0HzS9y^JpOH>fjg{riLJ=?0y+helGM}tcS)7t?Ks^VEbheJ8d6?=hrU%#e_iII(z?m*AmAbjHUN1;A$&O*rUTQF<(KyC1qb!<-QoSlDE>5nWo}b*W8Y7a~u-Y6&^F|)3L}8Q=5t$QZmS~bb5?n(CYm~TC4hzx{BMKBHD`#LXS6Go&RY~CP|JJi>sZ=s?wWp9eNM;HRjKTSCsOxYun;}dVfsiXm?)uSI=BSNR2s)HaCVF;~hb<09h=Cjpp*`zKgQD2nZ6c2+a=l3%#l^gnfl`GG)N2q34sTu@KYDoFtn`VBRn3cn%#uQ(Igb)-THrXABgs=LNDG)Gs+=IvZAn;UAWRS`ijmKCSzOuQPhK6$B@>BkzR=MGrVHs#9HkQwawafhUp_sUILzmf7DjUeDJa){l+9+_5Je23a4vQ8Ai33KamGf#g<N_tn>AsSoGn5SRm=|@@Q^5kAsj0b#r<IxrPa+J&dwg5)H>E}sZ>q?73IN9k<EFA$VdtYRG6nv%(###n+oVvS-CKbm7RNC*OS|+RKAc$s<O}r4W@U}$#em&FyeK1fAAntNF|^e&GaX7scZY&$t+SP;X4SL%=R4YA7)DgG0MW3T%r3YkuM938^yUo;b>rcr-E@o1jf;9E^|90($E@Pq{#x6g$Gpx-~OR})@e36wf3EI{g45(VR9UWcb3(?k_=WZtD10OuHXA^;NU2gC}yBcp+<D!z1yI4#Z&=m2?P05*LDKRq*16w4kQqGct4p>Lx%=Ei4>u9|8_c&C^V@_Gz~+!-mRl7R3_#MD3aMr-ne&kprauSE);WxWZzM)jKy&hf*~lA8_ufG0!@*m0OLid%PMS~KR7$9U0j?rnj^>C3JX+6Ey)u9VClw{ql1HVDwE9TvaRn5ca9Fh;3i=td(v0Pb#EtjGZ1+8b{|-LS8^wFfadefJB6ccVt8Z!D3e9a2|Qg)91I*Kj}8k>Hx4EQN(^luq+lh?Bl#kpJ{&kqX39Z4hvQH&mFzyuRM$B?Ul4P}T<+FEbscCc1}>Y2k(=83`T6<9gNsKOm5c9vJ=IFhthF1G*=`;`@WU8P@Ia<Hw%wFn2tlz7$uoTOG0l4NFp01<EmhAM1&QD(gkgBR^8g43@6Dyt1)4bd!DJ8`_8lPzhIj5O8p#oOD1)Za>IIM#p2zS-G=()Ts=6$xh=c;StDUoIRgnmS<YV;7MY*IKU|TtXU%LG8>BHXuM*RBMztsQs;-{C-Uw?XfdHMcL{nroA9{=?6<?H7kUcRmW>C5YvkG_BQ`ttSbxAnh$d;j{U`!629eEI5){+}P-K7I4-{*O<dy?L$w=ht^HK0bN&;OUEJugZUa_wnP$x0g?!Ts(bi{{LS-{`~Rh*FQe~{@KIIKfZnX^yU4#H?Lkkep&nfzJ2-p<<p0^Z(l!sS^7WU{`~dpFW)}A|M>ZpW|-w>)i5j7E1TnHS^vIPv)Yy8K<8uu7iCih5?KnKwyh}1@gipmYNYar<L7ajU>HV;weN#>0~m%&tPwxy2&N=NVVa~%(e^`2<s~|fv5XeEIJFE#ps5v@6a8%<vn5HVsLdiAIe(;q(JW~MyM_hNACzmRZfUe?ES1cPQLkF1iv9Q33|b&Xo)t*$#=VOhdZk%y)tbgh^jvI&36`OOn9IR)p=HDfQj!(Ph@6NIWMPG8FyLdsdg-)8OY;iBDqQ4LKT#=BSs`een{8PDT!i14074^e?W9@)c)~|m7F_KS04mFr$W1!*y?APwdR;g4(%rHqSthTSoj1FRItDO_BoNr!OLUhISReorF;_OuPX|kerdO<LIozS8-_(fWXt5kQRj9VS45Pr3<WSw9+KRMBG7PQy>#_)RlwZIEP@z*zJTqv9T+Xv(xF(7ZD!ix*OB6MKp-GR*z;7*Xo$w#)fM`l(4nW~Oxonhl(Xw@Q?-yj0B3POfC%d4&J*z;INRcFO-+<DCDooKRD{%i~vvXX%V^pnjrT!q$21e72K}A{-1#eZNhzb#)FkIk+6<Xv@1#!M05~5e31oqru@EA%Gp(-Gmhrj^Xd72DbvMN3_Rgn?aWKUg}g;PV(fnTli1WI6n`wu<42bnfXzz|Q2U(0tTa}|cl6-acr>!{e3Q42(>P@pCUki_8?xsbysl>GP2&WWydn~GJb8$QFrSV{<x1<-{N)sQqom6i}%V4Mb}sPrjA-OZ6?NabmcxsWJ&f#rf#hU1kphNF~aajwj>BKydy3l(hzE<!Xh^M`?>^ua*~!!UxI=t+Ecw3Vt5B!$uw{mJZ5GGh{ekdWDt9F`q`)gnv5jQu8xK<NRlkfjLxyNy<-Su+NJ#pq2BDoGfHR~J!$CO!f5Jq6e(j3ewU#}SMwol?*;NqH#|6o>DWC4Gr^s|-O)$`2YLD;uc{QW)vIk=#xuNs}Q6#L<<wdT%eEYjP-oObtRiy@yAKErwum+ekW}?AhHZK@0_Zoa8|+d-G5%k__&!(Fj)99i$2vg8zQ={)6M=W4TXLtouHaVgYn9jVRbV7fQ>r%CKepE-JWD8mA?Wsk8hdF^99X#L_}jHu+d0lbE_TbeKQN9AxVlBhLN-zOsLq%AyU>8#BG>RNrnYovp%h5-cx~xRKf`7zE0WjY4?l;O2g!OmdWc97d63y6b=`qNLNyqbQM0cS$(IT)lVy^#1WlvvE}}S?;XN8#ExE+7iu%GQ7-T0xxu=CElAiS&kzG?VMKEcJ4a5hYofR_mT;;&J)Ak`TouA?Mxa(25e+FmF`RLXVZx$jM#4%(uuzHWE!b**o?i9EgW7uI5?`4*z|8knap21%9#-A@R4~0%H?mS<vcqXBx!`srn3Wb9=m?8(>Xb=w`+|dsp>r9b%xeaHeZcM-UC?!!>qDYhg;jVUAeZoTgU*C$d%Bs>*?-;{S=Z*Co33e^HlfI5%8>J4WAw?B({4u6RCXK!e?yxL?YR{p4d33qcbzvLZOiB-^(7Um~%FlD<Fr--b6w}Z$-%hjHh$S!6N}0U*J#xrBFICppxHh0GRBwJ3s|*S7s9eh(WT*<Lv3O?b>(A#O^^BD&&d!otuRl2S@oLxM{95bt6-_dbF2H9c9w`cy9*q<JSHGc-rRZO)8ts4D9Y4?PI3RO=9`vVb|7HHdC|PQ8H76lQ%bZbH+rBKmjkM3xm6d)rnOUfstY%m%4Rij?beUhGpRl1l_j&u<`Kzqtoxt&MTd>p~ml2zNS^1%|@+!jMaTu0m4a~(Ab*LV!bc{qZGo!r_>3H&*7;ePN2-0e8#X;ES)bRB6-RlOC$})GXThm8rRk&9z(*(97NWb3qcnsi3&r-VokV^I9_FWHU^O=^!K{N%en}&5wszk10gbi^@vjZ4_c{gmb7xI)3INid5aWD1I*-@sY;9Y;S^9tn&n)rHb(>z493B1`db$O$0JZ4q8QTIX&WHp0X!fu-cfJqCIyoV5K=@O%?ENxR!JtDL1BCI#8M4Gpou6(*cuNET?8^kF$=Kk(L(?P3Wz6)eE02}&u@SJ<>OyJ{iRy}(~F;8JimN(`R?+SX@33m?CA?|_~!lldhM^De}3}g<L6J`TwYq$zkhi1>dE8B&tAU1Jg)!k<GWWco?JWw6j3Sv*O#|%pFaQTA^4q9`TNITKD>GM`1$>_7tQ)Ve*O66-N(yU&mKN2YybO?zkd4k^YeFapFgX%{`K>huRnkL_V(k4=k=;-0VAl?2Y<IQQZ1L8wQ|*J`(~T%2*`W7A=Tu7t$M<*AS}Zwin2K0X)5Xp%ZQZ3EW}Qam6E!~^Eh9MET7(&^^&qoB7#02K0Y&4Nu*YAf(^x*?RrI5WMNNZ?#9o~tXf%=NNHV;ES&vNEnBK)XvTgOY?f#?%9Gxnz8Z;AGE4DHPuE`UwpP*VopP%g@OOyH0?LTI&a%;1M?7YiXi@<N6rDdaL6Ba+8C)z!Lk;~@WVtnp7R1m(OZ#3GBz(0<^Yf9maaJp98oNz#{)M)7YHE_Euv^?>s8fGnS|)&TYpV=MK;tE+t9Rtcq;L)e&SD$wf<avVtxq_nyZ2t__@-DX*N)p(C{!k;<9SkKfh|S?Rh4gxiwr?(x-V*p60pN4MzUNaW=ht5O{LdJ&|UK-RXvk*m0QP|V7yuZ$zSJma*K@mEk%E1RwPxI*JX|oXv{v<HL{a4XoSIOYGmrW!j&TvD&iu^OxVX@sz(IYO5@D+uFbQ0ZOBwjv(XGhWtr!z^EgScVmM%cVA)inSpuegE`jB>V}@NR&~z{a%w2h)3c@zd2Lq}s$q%#=CofZ;fFaP;-@eT$tJ@&dK$vafO7G78fy&SfijPe8?SHqMR8gh~qps=x^g-`|m?uaWa@Z%*NN(7I3NS+cp>O-x)T_6YlG$tooWPJt%9t+-qA)kh6Ea7)urLdZ(nHYzFit5dj){SQLbIZLY|!Ec9SE|zs0#O0Rx#Ex#azZdI@Eu#yH~VG7)Pcid-kvHB=agm64=b-P%+bckTUW(gE`z|AbAWOfI=~pYkZ2z0aFn32!?!jb>r-`qMO5tSZ;efIhJ5aq7-9M$>oC-U6h0tvP9#dU{Rtu6=|^aT|O|6^BgCO4>g%t-#^@QjNIrs+(~8gO@iiT?p#k?IoLZ&mPv+~b`9qa`x8JxS&Eq%8_DN0HxJSkj8bOYZWOG)D`g@y;_`-R6v^j@MGU6?aCNhD-s;prnaq;MSzsi<yGUsT<y><G5oCUvtx-$jtUs+Vf+CSMQ{CEIo3Y)zws`~sVWCQqBO`t3{@v}p)KLRL?31JWyItGcNl0f=yK5|o?DYcmuVJ`z##w|jnUUn4f?`wl5Kf|S{?@iaATy)!Y!P@zc8G<M-*s)C0*h(4^a<T`IS+Y(79|XCFOnYDz9It^7sz&L@o0SX+O_SCgKPoK)Y0)<*AKe(w-2+KoQb=~ZYB@=w-ZUUU}as-ksJtf+XqJplbUhZbJ_gS&BL`r6LL<6iv+S?7)(HNZrT<hF&r3l@1BxzxZ_x{h~%>HfK1%DzTG}OYn@igt=pQ%lVmsnyco0-93JlO+1*R*9cH0SZEU1B)qS{gkjfpUs*bUdbmGQVBArPj8V<WHl{x4>1gMp-j=QGvxx>T|NUzzdd)f!3b~34f?Spj9HW|s|#bh4pKTIm)wm6!B;cO~Dm??Q?w_q%rhw{nHpz`0ZY@8m~TJ3VJ+3G*7Uz5v~a=ogbo}JQ}hCc-nI3QKF$&zQJA1R^)E(ukRsL;e5gyT4ew>h#>Ad22J@D{F4ksTeyaUTF=slf@4BtvB2KqgPsH2zG}Rlsi1B5};aPYg|wSq51otBm-4wZdo`tw^!f^_pJM>lLk2bJW;sD3AOm&LlBsC@nFL78t<tjO$oArtt`b<VA+^wB&OU=i@~jgW+J4X-OPOFBFQ1<UXNWC4<I`^Qj!}IabaM5Y{9%h*Ivhcv=!Qjo@kEW@qw)-xg!AtQa4vS8L6RRcSWnCfgl9L(>e+aa6!_(P9EHNq`RKJ-(Cs3hReqjOQ7rw|)v#bcKQ_l5_@u>~ba&gAsx7Ewt+mg^}5ne6ASqv`-DWB+}>tirL)FlcrwLM2=f!eBsmY^@>`dc~-gi;`05sKYjZ4^-H5{eR^^E<MZclUtYd$)T}>!{psPeC$C<=2KL$dU!Pz7^y8Z!UR=JbmYaWm|N7aphd(|4@eR1$-#@*-eE#g>@w3<EM&ln}KYV=s@}~zsJuj83fB*LR?U$!NzIgni)~^58*Uz6ne|Y=h<&#>w`HyekKL7mX<Cl*=7%EV<l2#h%@7kCsTV=Irma4Hx@ce917D}on>XBf$aiXpP?50g6v>0ieSL98OrB!}m{;tt6WZ_Wc7;b4H*nB8!nzD+r{8Dt`_(8pC2--bLoxitm@_o%RG(p)BmhJ}6AGMDS%aDvc(E#;O6^CQAzo$kJ9LtkbSNFg@t4HH?@SN3v-(#}n2u3oZD9_E$*Oa!tMi2z6t}Mjr%$drqfSfM}V)Ir0)Ks`N8siq?;ga>hs>{R%%`JqMYHFuemRNC{i!Ux5Yam7`x-J|FB2Ove)XYrRcZoVBu>wsxXQs#DK@p{BR-guNUcXna45&)Ap_jwqkj#+vMH$mr)gKL69Bm3~AaAhYKtwaxwuHxvsIm|U%NpNQO3WfE1ftQBrrfXV8o$OzLSen6K2}w}q%9U<vH&^8Zg&H4RuPOY;*+xzce2Ad4Z~1|7$3JyV(Hr&3<IyZ($l-sE}LVb(I~g)B7VSqoE0W0R`$;ZL{(x<c@?5?e<Vc8veJ>6Rf3oc%t<`2G&xLKXTrgVNK5!xNfCsVOmP>P8k_Fv+s)@x63dacnX!Rv_eQ#2Bw=yZVH?Qgt{wrJ#4!8hv?rG-4k@WD0{^bR?_Se1%syTen*o;_RlquoC`}Myj~kUKoI1xBNiG-w2a>3Ron94!em_M~EdM~%^sQWKcg!{2)3tq+DArk=a^1EMr+X90LJ2}Rr(<j?Te!V{AmuS)Y{KC!9_B}qJd~&HlT#54LbC%zE=T>x_21t+yI*gV?f^0O2O==90BR`3Nz^+REYh;XAT@E34bRTz1<K&LW0|{mcXMiNW~ggBbC^agl%1F!AI|q~9~>rH1#H6Uxpj2VpWIEDFy?ek&E)orz56*881anFgXQ4#(5^&clT*_%3WAHpK|T*%y>V^hv{7wT8M~&rec=OzqZy7iRxnT4mtsX;q=d4vx;;7F_g(MiehPw#3TboQ8A@N@+)HMmQW0F+md^|xBn}e_?zOolQ@KR%UN)^`(=*cnIG@T49_CBXh{F|!kYsAN@5n$Mw$bGrO=QsYFb{YC{&!pF7Z;6|QL$-0UtovlRRhP#)A`Apcdq@%)<G%*9TZBFW8*!k-tFCcz~mc~)6=)p2g8Y60+{@a%{i5Zl6?n<sZ4!hYRXrH;JsVhTZi>&*YsQwDIl5Q&3$FcKC^}+xjekvn^q?$rk9H_hT_G{ZRtOL_wO6+N5{?6y4f5$X*B+$qUeg*Ds@^cgta_S4xx&i*yI_!LV8j#Ns?Sy#L1RQgmXoL6itz)k7+R<&Zcp;B#GF4NrrJBL=XnU(&v0h7RVsRR2YVPpcpDg@e5c(RjG3mWD|vv<{R}vMHU;!6|?Ls^H?naVF;n}RJcR3=e!3hk_gVaErxA#OcX8>JU81=<PuGB^EirAzLregmv|P99ToGA7Rv*fRtY)=bKWXVcO(fQCBIVepNQ(YB$XI}lh>L9dc~6Jrq%TLT67Dvc9!Nu$>k}t$8tP_A(V!DLrwKmrK2c#NYWoT*3TH8Tmh6v+QN0|Tvm8$0Ym7(T!TIVI>A!Qh17hcte>kTUg4Mx$P+!0J5{wL09)L=(QI&~l3`S$0dLKW6iJ3rIl<#zYPOjOL!lCf0|}^{8SEwk!3-Ps#p(|fiC+c~hX(`U#yKyE^j+ZIvBi*8`|TTW`fe^Ch(wRi%5}*g*bR0u5-xYj6|=-@^4+KJKY#u3*FS!%H=5?R7q6c_fA!|gyL!7}efxa*<HJYKUSBr#YVA+&E`PZA;pwv{W}{mE^M@Bto?iU$)8lIG^!RU|-aoti@rUnUl*;Y$fByRU-RtKspFb`)%dLNX{o~J{-+lby$9AWE`p>_7{r2YV=l8EoSx|LN?H}psy?4jb)mEv}4hHAE?PgpeMa_~H7gxfyy1Yu#f>c?WkA+$fWMzR6X>NHf7Op%n41N_7<&{X}ZmTJmbm@?kSLYX(t#-RgaoW1EytukrJ!u=&l45SM_-}te^SW)$TLT703pgir5BGhyS+~iOqBN@Bcqm-r+w%limF`<xh#JB%w@xv%w6w4uGX+yo)@X`}#lw-hQmqK=GNVKT%ZsLVTGtd~n~pE8+^v@GH*`aj_fUi<S(n4(>gy|5D5?;QYi`PQJ9nKaQUs4)?H#(h(K1JXHku{>Tx5x5vBo?IS$a4)8xb|`LWq$V8}ZNiDV0B#<T$~G7vfP(mCkjA-4O1^BM}974Iph{y_m@nv(wY#H@kNMOXC#jpB<gLndr}gsKXO3hs$Fpkeh0u0JDSLy;nBPsy-vjn&tQULny^Cm5m~d`@_B<0bH)a#waovas~*ErE9VlqoSc;l-61DST>Bcz0{t^HZ?jlxR*v0jv$@xnTfIdU?Qa;2x6PGPmg92{V5JW+{Db3eYTLx4l;QX@4s>V>b>(u&A3C$Wv|=oPti2V$V)gi7Y;iLJWn$wv&zqTLIDV<sMc2WyK6fR`{?L!_r1ehO2=`x$2~oEc>OS$sS=QT(mpkjIqW_<l2CDMc6`PILr`CWMT+)-%^NFb;lfRYL~q=<-oMpu9$V@N%LRPy*$u{EX;O=0_MktQkwpOk_l>Mg*k&egc5QDSWT6^R<x$72OyAais-VC#c9(rRbuh4-Piu(7IX)B2XAf>39B8=R;g}8}2%I0>LC`6?-Lb;KStxslfqTBY(zn%YRGV$ZVR-%C@V?43Bqi2kGtN6>T{kxOlSlix(zI>HHhS2zpFT<yRL6wd?L0aHR*)>1Q{IUQZ#uExzm-arZ4=W|v2-q1xOsS_jJsSDD=?hPrH4|w6IjMFULdki>Nb1z`hV-&IJ<vZuT+dNAeE)7l44eYRh19|%2|F0LUEEe!P)r|=}r`iEUqB9jJ6><jOM63*m|07NI;)pf>B785`R=Uj18eUASIr>&?Nyh7HkO;$={b*N#UiqRnx99l3FR%o6ZuDokkSGV47#V2FnvQDx4`owCJ)VEMG&5{v=CqV=}{WZSdQrB2Ifs1ScO0DoZR-oJ(a`_MB6Bl8@38Rgo4R2)fGg+~RS)Pv>N#T()MXEfT4O3JBmN%ImiX>I}d8TPES%zPiShSt_2-lT5(gV5pkFqG1BVXZ<CC?Px4R-7Nx+FEP}KrLwHBn)A+DoYpZk9h21U%7AW^8lYOUzNtDThY*CKMRwK~s0eL(6@n#(^#<oET$QC3A%Z0Q9#5OC@D#O>E)f1`uxdWAc!pUn5K+HdmyT-^fZ2H@<nbRX4@#!Ni1Lw5;dR4m>7jtzrB<T_oDoUZ8<=%jH7O3`q{z>O=EHiOV^?rgrv0JWIsIH<q<E2l{hs-_*-~_tU55~VY{{v&%#z9zt76a>3RlmqI`A!h_tncMKmYpi*G9Ecum17*>le>oy?t8-XPSTd{KKnfPhWpHt{v;OKYsZ5<l&F+Ut8r`$NJ;jcQ0R_pFg!qHS74lKD~K)`SQuja<h3_{rlIiA3l7%d{V8oYx@8E{OhNmKfiy;(IQXNqqm0p@7x<RM5$D=BB7<FkXqefa8^{7V!?Pswzy@I5TtN)KD4A(6nU4#`B-=<vShX`nayx`Jh~8%YbPyP*S7h4OA8D4)MnYxb#<2jW`=oulg_D;A*n!uqV^At3=VIV#{@=HYX0E-LP+4%7)oh;aDIL@rb=acNy6Fa%2H%i0o}#!Vbt7mI2sbPjxMYFOniQMbzUhQn+z{)r}D*w#|~b%x)Y@$%2Kn@uzkv17~u0bi{BXP9_`w!mhT89sT}mp2j^%7Ru?dWk4NTwAzB~|Zky(#b1UIRTB2Jbzl_A9@x@hASE{tE>|_#0lkO?!`0bvZeV!nx38!s(Vxn+;Qz@|cG#J^Lxm<CO%Ak1H_3H!OJ9SGPlLXcu3;EqemPP9eBp!;y;&WMvWy{Pw;Dt~mjPQbB81nk|`t;QF$jrozor9zy6h|j*Besd7?wuX2khj_GBa@Njc3)D!=sR|Ydpd|8rn}f2@^9C=yL+~)f~Ir}?9^-^9Nb3*HeXw%TmkQ#J3(6{Sr_A5Qx4bE$gQh8J4g8vKIxeR5P2}TzrA0f+|JR-ad&ce=qSOFQ;xA2TNp|o^dwo>IpdnJuTuG=qhSv3zw-P4-nZ3h)Rgjw?r{f$o-{8pG}ByhIA(57_IGXWrZQ>GX`7jHjPG6FTuY|P_8I&1#O%RA|89C;n4Xw+JHx3|Vt9X3a!ilAJxjS%e*e~vWS^P#**8!um&)8yul?a#ckgDcQq$_S+h?`5P`auxx>c*nFjFM5byprEITk=2juK7En<@~fEaDPO*ExDF0V5Pg;2e3%;YBZ&Wf=ir#F-|EY#iknnq|3jU6lo9q17(ct}85O)lXeKCSv=V3nDOxo)J)ngG_WTnMY9v#gZ^<VPpWwK{EzSN?47eNk59XMUD~#(2tA|!Nxg^q__u?z%b@gy;-|aRt>A#@i<i+V_V?_R3w<0Ns>X(3KvTNZJ3#raiGXJ;?I$o(<^bL&?pJH#aw>ct1z5!q4N~GM7sU5%5p7DXMt+f>b<fqSW08o?+`??;lU9UlicB1RiZ6Al1GZ%tk17<T$#kZ5Q@$@ot!Q<1dO<w!`+TKftK$J63uLJbDn_8P#s0(@X~6vPbYN4w0th-lmc6Ej1X8j9Ps-@uFiytd7hdL`Ft9GA`**Pg7D2n-LldIW4sI_!9d8bv!}W!GrLUC<DVC$j%qNPwA`<7tfFfnZ^YvhszC&$crz68d);h}m@i~0fIn`RPpV7oI!d8|a4Z~?S|Y<9QfMe1jV>F<qQuMdSRk|j;&si?BuQF&{p#}ThmY2At8BJDKYjk@^8E*;Qnk$TmyeI0JbQJiRLokr^w*E?0lEHEu7G%7`Rj*QmrtKQDL1WZ)BMNRPp{uReOjuRR;~WeZ{Obh{Q7kf$urWO+e1C0y&De6r0d#3D7F-u<CPUq2r04<iLAzWLt4cIa&bAn7@XIu9Cc4oSJzh;*OsN0CMx%&*ji+MbwjjDB}v~*LB)c1&TDhp?R`=K^xSa&(9rFHEoBB%CB+koEW~C>yt)n}bbLM@jE4zUVpdUlem=SuS>WWlDy}ojOVP#E2qjfbL0{g<C7oWI!)2T9O)vyOxa`h3&-85SHkBu-u3LRw{ns~*ii=g{xyXXgJD1})@h-;sqW}V<xJs6#c_J1Gg@W^t%9liCd3Sf(?wFb!nd#Zes72H<H|w04p542-FA%uXX?M&z;<@BCDhYRW_jKPL-mzq9R3ZVt#(dF3n!?p(DiR3*UQWm?+obPpjf_r@kKLK>S>1sEm5#dI<0GCz-|m(MIqcKksp*A-gYGpv4I=5J(>9;TrUvo+)t;-p1N|GSuGaeG*;x<|yqh9JaMrwQVti_HVsv<GFP$|f#wVw2Bd*;W+Z##EIXOGyaECJ6UAyb#^o-jxHMx>Zruz@LX`ch6-?dyil^GFwdV0Ehhqr3LoMmVG_@t(&y|kjL4IJ1zMq$z{QlN1Xr!f*oPic1|gBKZ;;smC{ppgQA0O0U6@(@+%C{FP#OS9x7OSZ(d)8nS8{+lRhR$~%jI1GaoUnUPq2=N$&BON}HfeJQ^DDX7fppkh3nPxbd;`x?NaRJQ5fauIK9gP>b#d^~cx)`BknlsY`#TKcmA3_-1K84a$5p5B1fNlW?L5mVd+xZ9%PuWPG#o0PX5fOCS&Ve{co(pP8j8_|0KPwxu>2c3dIFql0GX;{Kobdv{gH1e=FA{d2i=q^!jpOk`(Qlt)D3+;%CyU{}fQMoP{-VT7++s}~738Yc0s&_ZNSzr=!x-)L`kg36G{_YQD+HWgH!jgl8uk+)7`xmQtuzHrTqS0G;W==RQ$doAHET?!8L94`opbp~suIef95v^0%mx`!Cxgix<_Y)$K@M-o=v@@{1-xz_C6^UJjFN#s#Ou-7Gex4s)!POm8KM&e8kYwx`O&;YMdrMIzYi-F7KkFb<ev+;X1S6mF68iFbTJb2v!+F<_s|#^wZJ^zRKd>QefIj}yI(8yid?Rj-#>f){PMk3wJN1*_1DiYe){P#0Ntuqx4wM(`SsH$idEJdmFi#Lzx(j`l~uPYMx*(!ukSy7x-4X%-0+>g@!sLljcF0X#n}8}Jhr^dm7)Yq#22IU!KEmsig!sNxU~c_>I!NJ)(*42aCdPob{DVcys&?8cm&ihFby8)Cg?`Ge{}TD;H{~R(hS0p!B}u*E*{B|Vw|L+^AVs%OL<aJH!xpxAsU-s$V(<KZyoN<&U&5RDc5YzHk&0pQyyn<))n5r#pIFR{+^+mH^+8M(ilwzqYK_pa1mgWyvzg_=4T^|fg>8XxV7EsnMt>OddzimYmbLVr(NStw=JF=S|xL~>1n6UKfRjR??a(K-1zRszYpHNr;F@uE*uPcWBz!G#t3zF!Zr>*H0HT>cYm872WuIhnh75atnbS9iD}2w#N<*sF|da_9h1{zZtrp;nHUuR$CcmrU%z#0+u%fP{NnWdv{f&6NhQ@vQY_8jd8i!9=g|zuqawi&9XJfr2RyJ&5oKFAA12cZhOi`|ACtHccw9X`Hnc0eR5om2`~(alsvf*ZO{N(N3?R~?mvYo>fhB<fBXvd!W40^@`jDerG9;`YSIfHA&FCf5F_ouj3Qn<sd=hiq$zdQdktP*@kvS&}!V`{HDK3mpdNGnD3Hl+$O7q7ROZ<-Iw5r|dfEgm6SArP|b+{&B8fU0B6;2>_hZE)~@L>X9E>5^@1(~9VGN)=j%d&bouGFx*eXcCUAhkderoEn7Usj?}0}ny0bJpV`X^J;Q(T{nYUQdSR)vCg<t99vyByy5>7W93F!o_F-qFkXl{~V6f8nucOa{+I_4XLogz$>gX>YMe#5^KnkxFp;ra9MV{<{UnE4y*f7oCyR#CwU-3C6^F9=#NEw0YU^!5yL#5XgnH$N+!t*@nM4EL~k(a@khK6A1J_x%kPalgAt5HqnTnTIyV=Jg>adm)**jz*%u8h6w8bv+<S8Q@mCFumu#8lhZjG-xdi2|=vuY@%ex<*zc#dHsjN3m5I|mD>Xz9kH%^TI_2tvoXNS9qp<8!u4-Zd_Y~F?_BCvcnI=2v6E@F!XGPW3vEiWyt6lHFeUYcKBT$-O>heS@;+1qrvoWKj*uINDF2pPILINEpT&iJM<LtyT?SYT--8r?<3m0TnqkFCV#S926YZ0x&c9KiLQGx7d4H05*vo$`1+D|-XT;kCYg;NO$CcPV^`^aEm#1_KKRP@Y+tbk5A$rW})@zPlTU)8?3Pj@vy8o44;0Gj6ZVHaF|Jdw4K_4qUl@<IeD%(G8VkX3oyqrzf>iso#*ByBrA25>4PuFNz$IGH4DFfFKj6GMq$`JR$Puq8vXxJ~^ov@=cJ-CyykKr^zBG00gxk5fnIwCM+rrPap9F$4DIB<WzsVS*~kZH!YOilLr*b!#H6DVASbMQ>?%uP@NB;6O#ud3+R%nlXR$7tEzgRSe7PdZQDH0WKb)NGwxa29t-OzRO5oA&E`2I0X`E|L6|QaGCwGY96<WnJ%Wd^-@e40a*vNE2!Vz*F<P8;OxpJ_f<;>r6DsTKEnJoDpd`+13ZtcY6m!fuY>q9OqAWaAblF{YPYMyJ3d66c{2fFfJPxO8X8M2u&QTye(?IKd1)MhI)vR~cGv^8B7*t`!7<v;TNpEP{=bj7hl5C`axO_g}T+o{)1Sk%<Lv!B6`Nc!BO!0SzayS99n8)o6hSOv;S#$-1{@HL~>4>B6p@BJnI2H&jB!DsA`|;VQQmq7p-zqmgKYj74WR*2ZtLo<G56|DXt(qlSRipIfm#;6^cLr`v4&EFdoptWaP=#<H7>_UAosVaz%|a-)9GPES-P}mX`2L0?=yKcUoOAKjf&5<gt)AOslM_>}9e5N9MZ^AJd~qG{KYY&)mJh}^<XG(8$UA2Jla8P-99`b&FLd>SRs{V#w}ryC&iTXk!$zfT^_6P?+XO)oDI7hHP}?Ht5l#?M`b=JIb(+T~rdb*i^yzJxK}niH(RzfQ+GPa-JSb6Y%dwLOomO2Fx;SIXzDE%(hLZ(zk+IqLNg9_J9=XrPPLInVB=oYPZOpy}^qBhXUuj9_jB{V5DF!E7T%^?i8#2Vx_9^G|7Av7t&RoPj_8G^aL{bP@<wB;Za(%pPo0*w%uQN<Br3a8Hr_JrThp-e?BICTs4>6j3)@h&f?sGV#Mhnv(-|Vb!mxT$7j_K?$!MlQhDV%{rI4{QwA-4wrZy;GjRe2u2g~BtoS-;m84(+9>r9|8l1hN>IKP(8vrICEf6>|st{_sL{gAO1b&?u2WAbdB0z-#Z`)y%S@m1<?H_U6ZTX1P?;O<lLj-#$OxxYm7pbm-31n8&v^v9YwY6puugR+smWk_&d*Z_AJQ{7cJ2JAK!NdT;fNOuJm0hokND<9hA*7=(?H>K=~?44_M{z;_l-JEx7NWoV_LvVEPGaZ&*GB%OLXoyu|Bl8u|@oymKggfn!$fY!sEcBfs_j4o}|X4}Rnk|8nt%wMnG*R9eW$vr#c-T{M;P)ONVH>!ekjhwLCT&_KwB#Rkiq0DmpfH-b<f%lRGoW}Jyu)kr%?e@C8Uhf8y&MS)uI+>ddfx7uU;iGJhiDYgj!(K-?2;?lfpTOdS_k3<o(CZI|!`u5CfsfUSrI&z=TXpT%=QsMgy9ciKIH&w8JCi3Tr=5EJ1pJ)$v>NSN^Q3K6Th~sT<>Ql%UOu^A?sVF1qpA;_w2Wq1m%BUVs!=uv%4J<tZt(=m4HQWBTCQ+&r}x(X1Hl6v#s"


def _decode_pf_eq():
    raw = zlib.decompress(base64.b85decode(_PF_BLOB))
    eq = [[0.5] * 169 for _ in range(169)]
    k = 0
    for a in range(169):
        row = eq[a]
        for b in range(a + 1, 169):
            v = raw[k] / 255.0
            k += 1
            row[b] = v
            eq[b][a] = 1.0 - v
    return eq


PF_EQ = _decode_pf_eq()


def _rank_classes():
    vs_rand = [sum(map(mul, PF_EQ[a], PF_COMBOS)) / 1326.0 for a in range(169)]
    o0 = sorted(range(169), key=lambda a: -vs_rand[a])
    wt = [0.0] * 169
    acc = 0
    for a in o0:                      # top ~35% as the "playing" population
        if acc < 0.35 * 1326:
            wt[a] = PF_COMBOS[a]
        acc += PF_COMBOS[a]
    tw = sum(wt)
    score = []
    for a in range(169):
        i, j = divmod(a, 13)
        e = 0.45 * vs_rand[a] + 0.55 * sum(map(mul, PF_EQ[a], wt)) / tw
        if i == j:
            e += 0.012
        elif i < j:                   # suited: playability
            e += 0.02 + (0.012 if j - i <= 2 else 0.0)
        elif abs(j - i) >= 5 and j != 0:
            e -= 0.008
        score.append(e)
    order = sorted(range(169), key=lambda a: -score[a])
    pct = [0.0] * 169
    acc = 0.0
    for a in order:
        pct[a] = (acc + 0.5 * PF_COMBOS[a]) / 1326.0
        acc += PF_COMBOS[a]
    return pct


PF_PCT = _rank_classes()             # 0 = best hand class, 1 = worst (combo weighted)
PF_PLAY = [1 if (a // 13 == a % 13 or (a // 13 < a % 13 and (a % 13 - a // 13 <= 3 or a // 13 == 0)))
           else 0 for a in range(169)]   # pairs, suited connectors/gappers, suited aces

_RCACHE = {}


def _range(lo, hi, rb=0.0):
    """Soft-edged class range: classes ranked between top-lo and top-hi, blended rb to random.
    Returns (w per class, w*combos per class, total)."""
    if hi > 1.0:
        hi = 1.0
    if hi < 0.012:
        hi = 0.012
    if lo < 0.0:
        lo = 0.0
    if lo > hi - 0.03:
        lo = max(0.0, hi - 0.03)
    key = (int(lo * 200 + 0.5), int(hi * 200 + 0.5), int(rb * 20 + 0.5))
    r = _RCACHE.get(key)
    if r is not None:
        return r
    lo, hi, rb = key[0] / 200.0, key[1] / 200.0, key[2] / 20.0
    soft = 0.2 * hi + 0.01
    softl = 0.3 * lo + 0.005
    w = []
    for a in range(169):
        p = PF_PCT[a]
        x = 1.0 if p <= hi else (1.0 - (p - hi) / soft if p < hi + soft else 0.0)
        if lo > 0.0:                  # the very top would have raised: keep a little (traps)
            if p <= lo:
                x *= 0.15
            elif p < lo + softl:
                x *= 0.15 + 0.85 * (p - lo) / softl
        if rb:
            x = (1.0 - rb) * x + rb
        w.append(x)
    wc = list(map(mul, w, PF_COMBOS))
    r = (w, wc, sum(wc))
    if len(_RCACHE) > 6000:
        _RCACHE.clear()
    _RCACHE[key] = r
    return r


# ----------------------------------------------------------------------------- constants
# Layer 1 thresholds (fixed; never per opponent)
T_VALUE = 0.76        # value bet / raise
T_THIN = 0.55         # bet for value in position
T_THIN_OOP = 0.64     # out of position: check below this
T_CALL = 0.42         # reference call threshold for a pot-sized bet
VAR_C = 0.03          # quadratic variance penalty above 10% of the stack (small: chip EV)
T_PRE_VALUE = 0.60    # preflop re-raise for value (equity vs the raiser's range)
T_OPEN_VALUE = 0.55   # unopened/limped pot: raise when ahead of the ranges that continue
MW = (1.0, 1.0, 0.80, 0.72, 0.66, 0.62, 0.6, 0.6, 0.6)   # multiway scaling of value thresholds
OPEN_FRAC = (0.44, 0.29, 0.22, 0.17, 0.14, 0.12, 0.11)   # by seats before the button
OPEN_SB = 0.36
# Layer 2 archetypes: (vpip, pfr, shove, fold cheap/medium/expensive, bet freq, raise freq)
ARCH = ("balanced", "caller", "potOdds", "randomized", "ruleBased", "shover", "tightAggro")
PROTO = (
    (0.26, 0.19, 0.01, 0.30, 0.45, 0.55, 0.40, 0.10),
    (0.80, 0.04, 0.00, 0.03, 0.05, 0.08, 0.08, 0.02),
    (0.45, 0.10, 0.01, 0.12, 0.45, 0.78, 0.25, 0.06),
    (0.66, 0.33, 0.02, 0.33, 0.33, 0.33, 0.40, 0.33),
    (0.16, 0.06, 0.00, 0.62, 0.66, 0.70, 0.45, 0.04),
    (0.45, 0.40, 0.35, 0.30, 0.35, 0.40, 0.50, 0.30),
    (0.20, 0.16, 0.01, 0.42, 0.52, 0.62, 0.55, 0.12),
)
PSD2 = tuple(x * x for x in (0.12, 0.09, 0.07, 0.15, 0.15, 0.15, 0.18, 0.08))
LOGPRI = tuple(math.log(x) for x in (0.26, 0.15, 0.12, 0.11, 0.14, 0.08, 0.14))
# Layer 3: what each archetype does to RANGES (never to thresholds)
A_WR = (0.95, 1.0, 1.0, 1.5, 0.80, 1.3, 0.90)     # raise-range width multiplier
A_RB = (0.0, 0.0, 0.0, 0.75, 0.0, 0.25, 0.0)      # blend of raise range towards random
A_WC = (1.0, 1.6, 1.15, 1.3, 0.8, 1.1, 0.9)       # calling-range width multiplier
A_EPS = (1.0, 0.5, 0.6, 4.0, 0.4, 2.5, 1.0)       # postflop bluff floor multiplier
A_QM = (0.95, 0.9, 0.9, 1.8, 0.75, 1.5, 0.9)      # postflop aggression-range width
# Layer 4 narrowing tiers by postflop aggression level: (top fraction kept, bluff floor)
TIER = ((1.0, 1.0), (0.42, 0.14), (0.20, 0.07), (0.10, 0.035))
PRI_FOLD = (0.28, 0.42, 0.52)                     # population fold vs cheap/medium/expensive bet


class _Opp:
    __slots__ = ("n_act", "hands", "vpip", "pfr", "shv", "uo_n", "uo_r", "uo_l", "fr_n", "fr_3b",
                 "fr_c", "fr_f", "shf_n", "shf_c", "pb_n", "pb_b", "pf_n", "pf_f", "pf_r", "pf_c",
                 "bs_n", "bs_sum", "st_n", "st_f", "cr_n", "cr_r", "sd_n", "sd_weak", "shsd_n",
                 "shsd_sum", "prof")

    def __init__(self):
        self.n_act = self.hands = self.vpip = self.pfr = self.shv = 0
        self.uo_n = self.uo_r = self.uo_l = self.fr_n = self.fr_3b = self.fr_c = self.fr_f = 0
        self.shf_n = self.shf_c = self.pb_n = self.pb_b = self.pf_r = self.pf_c = 0
        self.pf_n = [0, 0, 0]
        self.pf_f = [0, 0, 0]
        self.bs_n = 0
        self.bs_sum = 0.0
        self.st_n = [0, 0, 0]
        self.st_f = [0, 0, 0]
        self.cr_n = self.cr_r = self.sd_n = self.sd_weak = self.shsd_n = 0
        self.shsd_sum = 0.0
        self.prof = None


class _Prof:
    __slots__ = ("at", "g", "ratio", "p3", "p4", "psh", "pcsh", "vpip", "wcall", "rb", "ab", "ar",
                 "cq", "fold", "epsm", "passive", "mfrac", "bsn", "A", "cont")


class _Ctx:
    __slots__ = ("R", "cur", "pre_rl", "pre_cl", "pre_sh", "pre_csh", "pre_limp", "pre_last",
                 "n_limp", "nr", "ncl", "rover", "ai", "lfrac", "chk", "prev_aggr", "aggr",
                 "prev_nb", "st_nb")

    def __init__(self, n):
        z = [0] * n
        self.R = 0
        self.cur = 0
        self.pre_rl = z[:]
        self.pre_cl = z[:]
        self.pre_sh = z[:]
        self.pre_csh = z[:]
        self.pre_limp = z[:]
        self.pre_last = -1
        self.n_limp = 0
        self.nr = z[:]
        self.ncl = z[:]
        self.rover = z[:]
        self.ai = z[:]
        self.lfrac = [0.0] * n
        self.chk = z[:]
        self.prev_aggr = -1
        self.aggr = -1
        self.prev_nb = 0
        self.st_nb = 0


class _St:
    __slots__ = ("key", "idx_s", "cls_s", "vals_s", "sc_s", "hv", "hsc", "hrk", "hsk", "brk",
                 "bsk", "bm", "hm", "deck", "need", "wet", "cb", "paired", "rc", "hpct", "eqc")


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class Agent:
    def __init__(self):
        self.n = 8
        self.seat = 0
        self.start = 2000
        self.bb = 20
        self.shove_thr = 800
        self.opp = [_Opp() for _ in range(10)]
        self.rng = random.Random(0xA11CE)
        self.spent = 0.0
        self.st = None
        self.prc = {}
        self.prc_hand = -1
        self.button = 0
        try:
            gc.collect()
            gc.freeze()
            gc.disable()
        except Exception:
            pass

    def on_table_start(self, info):
        try:
            self.n = int(info.get("num_players", 8))
            self.seat = int(info.get("seat", 0))
            self.start = int(info.get("starting_stack", 2000))
            self.bb = int(info.get("big_blind", 20))
            self.shove_thr = int(0.4 * self.start)
            self.opp = [_Opp() for _ in range(max(self.n, 10))]
        except Exception:
            pass

    # ========================================================================= entry points
    def act(self, state):
        t0 = _pc()
        a = None
        try:
            a = self._act(state, t0)
        except Exception:
            a = None
        try:
            out = self._fix(a, state)
        except Exception:
            out = {"action": "check"} if "check" in state.get("legal_actions", ()) else {"action": "fold"}
        self.spent += _pc() - t0 + 0.0002
        return out

    def _fix(self, a, state):
        legal = state["legal_actions"]
        if not isinstance(a, dict):       # fallback: check, else call only if it is nearly free
            if "check" in legal:
                return {"action": "check"}
            if state["to_call"] * 12 <= state["pot"] and "call" in legal:
                return {"action": "call"}
            return {"action": "fold"}
        act = a.get("action")
        if act == "raise" or act == "all_in":
            if "raise" not in legal:
                return {"action": "call"} if "call" in legal else {"action": "check"}
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            amt = hi if act == "all_in" else int(a.get("amount", lo))
            if amt < lo:
                amt = lo
            if amt > hi:
                amt = hi
            return {"action": "raise", "amount": int(amt)}
        if act == "call":
            return {"action": "call"} if "call" in legal else {"action": "check"}
        if "check" in legal:
            return {"action": "check"}
        return {"action": "fold"}

    def on_hand_end(self, summary):
        try:
            self._learn(summary)
        except Exception:
            pass

    # ========================================================================= layer 2: model
    def _learn(self, sm):
        hist = sm["history"]
        n = self.n
        O = self.opp
        bets = [0] * n
        pot = 0
        cur = 0
        street = "preflop"
        R = 0
        seen = [0] * n
        vp = [0] * n
        pr = [0] * n
        sh = [0] * n
        agg = [0] * n
        chk = [0] * n
        si = -1
        thr = self.shove_thr
        for e in hist:
            s = e["seat"]
            a = e["action"]
            if e["street"] != street:
                street = e["street"]
                bets = [0] * n
                cur = 0
                chk = [0] * n
                si += 1
            amt = e.get("amount") or 0
            if a == "small_blind" or a == "big_blind":
                bets[s] = amt
                pot += amt
                if amt > cur:
                    cur = amt
                continue
            o = O[s]
            o.n_act += 1
            if si < 0:                                   # preflop
                first = not seen[s]
                seen[s] = 1
                if cur >= thr and a != "raise":          # decision facing a shove
                    o.shf_n += 1
                    if a == "call":
                        o.shf_c += 1
                if a == "raise":
                    if first:
                        if R == 0:
                            o.uo_n += 1
                            o.uo_r += 1
                        else:
                            o.fr_n += 1
                            o.fr_3b += 1
                    vp[s] = pr[s] = 1
                    if amt >= thr:
                        sh[s] = 1
                    pot += amt - bets[s]
                    bets[s] = amt
                    cur = amt
                    R += 1
                elif a == "call":
                    if first:
                        if R == 0:
                            o.uo_n += 1
                            o.uo_l += 1
                        else:
                            o.fr_n += 1
                            o.fr_c += 1
                    vp[s] = 1
                    pot += amt
                    bets[s] += amt
                elif first:
                    if R == 0:
                        o.uo_n += 1
                    else:
                        o.fr_n += 1
                        if a == "fold":
                            o.fr_f += 1
            else:                                        # postflop
                tc = cur - bets[s]
                if tc <= 0:
                    o.pb_n += 1
                    if a == "raise":
                        o.pb_b += 1
                        o.bs_n += 1
                        f = (amt - bets[s]) / pot if pot > 0 else 1.0
                        o.bs_sum += f if f < 3.0 else 3.0
                        agg[s] += 1
                        pot += amt - bets[s]
                        bets[s] = amt
                        cur = amt
                    else:
                        chk[s] = 1
                else:
                    price = tc / (pot + tc)
                    b = 0 if price < 0.22 else (1 if price < 0.31 else 2)
                    o.pf_n[b] += 1
                    o.st_n[si] += 1
                    if chk[s]:
                        o.cr_n += 1
                    if a == "fold":
                        o.pf_f[b] += 1
                        o.st_f[si] += 1
                    elif a == "call":
                        o.pf_c += 1
                        pot += amt
                        bets[s] += amt
                    elif a == "raise":
                        o.pf_r += 1
                        if chk[s]:
                            o.cr_r += 1
                        agg[s] += 1
                        pot += amt - bets[s]
                        bets[s] = amt
                        cur = amt
        for s in range(n):
            o = O[s]
            o.hands += 1
            o.vpip += vp[s]
            o.pfr += pr[s]
            o.shv += sh[s]
        shown = sm.get("shown")
        if shown:
            board = [CARD[x] for x in sm.get("board", ())]
            bcat = (ev(board) >> 20) if len(board) == 5 else -1
            for k, cards in shown.items():
                s = int(k)
                if s == self.seat or s >= n:
                    continue
                c1 = CARD[cards[0]]
                c2 = CARD[cards[1]]
                o = O[s]
                if sh[s]:                                 # what do they really shove with?
                    o.shsd_n += 1
                    o.shsd_sum += PF_PCT[_cls(c1, c2)]
                if agg[s] and bcat >= 0:                  # aggressive postflop, hole cards add nothing
                    o.sd_n += 1
                    if (ev(board + [c1, c2]) >> 20) <= bcat and bcat < 4:
                        o.sd_weak += 1

    def _classify(self, x, nn):
        ll = []
        best = -1e18
        for k in range(7):
            pk = PROTO[k]
            v = LOGPRI[k]
            for j in range(8):
                d = x[j] - pk[j]
                v -= d * d / (2.0 * (PSD2[j] + x[j] * (1.0 - x[j]) / (nn[j] + 2.0)))
            # price gradient: "folds because the price is bad" vs "folds everything"
            d = (x[5] - x[3]) - (pk[5] - pk[3])
            v -= d * d / (2.0 * (0.0225 + 0.25 / (nn[3] + 2.0) + 0.25 / (nn[5] + 2.0)))
            ll.append(v)
            if v > best:
                best = v
        ex = [math.exp(v - best) for v in ll]
        t = sum(ex)
        return [e / t for e in ex]

    # ========================================================================= layer 3: bridge
    def _prof(self, s):
        o = self.opp[s]
        P = o.prof
        if P is not None and o.n_act - P.at < 6:
            return P
        P = _Prof()
        P.at = o.n_act
        g = (o.n_act - 20) / 40.0                 # dynamic gating: 0 below 20 actions, 1 at 60+
        g = 0.0 if g < 0.0 else (1.0 if g > 1.0 else g)
        h = o.hands
        vpip = (o.vpip + 1.5) / (h + 5.0)
        pfr = (o.pfr + 0.85) / (h + 5.0)
        shv = (o.shv + 0.15) / (h + 10.0)
        uor = (o.uo_r + 0.85) / (o.uo_n + 5.0)
        f3 = (o.fr_3b + 0.48) / (o.fr_n + 8.0)
        fc = (o.fr_c + 1.2) / (o.fr_n + 6.0)
        csh = (o.shf_c + 0.56) / (o.shf_n + 8.0)
        pb = (o.pb_b + 1.65) / (o.pb_n + 5.0)
        n0, n1, n2 = o.pf_n
        nf = n0 + n1 + n2
        prr = (o.pf_r + 0.72) / (nf + 8.0)
        fa = (o.pf_f[0] + o.pf_f[1] + o.pf_f[2] + 1.6) / (nf + 4.0) / 0.40
        f0 = (o.pf_f[0] + 3.0 * min(0.95, PRI_FOLD[0] * fa)) / (n0 + 3.0)
        f1 = (o.pf_f[1] + 3.0 * min(0.95, PRI_FOLD[1] * fa)) / (n1 + 3.0)
        f2 = (o.pf_f[2] + 3.0 * min(0.95, PRI_FOLD[2] * fa)) / (n2 + 3.0)
        A = self._classify((vpip, pfr, shv, f0, f1, f2, pb, prr), (h, h, h, n0, n1, n2, o.pb_n, nf))
        wr = rbk = wc = em = qm = 0.0
        for k in range(7):
            a = A[k]
            wr += a * A_WR[k]
            rbk += a * A_RB[k]
            wc += a * A_WC[k]
            em += a * A_EPS[k]
            qm += a * A_QM[k]
        P.g = g
        P.A = A
        P.ratio = _clamp((1.0 + g * (uor / 0.17 - 1.0)) * (1.0 + g * (wr - 1.0)), 0.25, 6.0)
        P.p3 = _clamp(((1.0 - g) * 0.06 + g * f3) * (1.0 + g * (wr - 1.0)), 0.012, 0.95)
        P.p4 = _clamp(0.03 * P.ratio ** 0.7, 0.012, 0.6)
        sm = shv
        if o.shsd_n >= 3:                          # showdown calibration of the shove range
            w = o.shsd_n / (o.shsd_n + 4.0)
            sm = (1.0 - w) * sm + w * min(1.0, 2.0 * o.shsd_sum / o.shsd_n)
        P.psh = sm
        P.vpip = vpip
        P.wcall = _clamp(((1.0 - g) * 0.17 + g * fc) * (1.0 + g * (wc - 1.0)), 0.03, 0.95)
        P.pcsh = _clamp((1.0 - g) * 0.07 + g * csh, 0.02, 1.0)
        P.rb = g * rbk
        P.ab = _clamp((1.0 + g * (pb / 0.33 - 1.0)) * (1.0 + g * (qm - 1.0)), 0.3, 3.0)
        P.ar = _clamp((1.0 + g * (prr / 0.09 - 1.0)) * (1.0 + g * (qm - 1.0)), 0.3, 5.0)
        P.cq = _clamp(1.0 - ((1.0 - g) * 0.40 + g * (f0 + f1 + f2) / 3.0), 0.3, 0.98)
        P.fold = ((1.0 - g) * PRI_FOLD[0] + g * f0, (1.0 - g) * PRI_FOLD[1] + g * f1,
                  (1.0 - g) * PRI_FOLD[2] + g * f2)
        e = 1.0 + g * (em - 1.0)
        if o.sd_n >= 4:
            e *= 0.6 + 1.6 * o.sd_weak / o.sd_n
        P.epsm = e
        P.passive = (g >= 0.5 and nf >= 8 and o.pf_r <= 0.07 * nf and pb < 0.22
                     and o.pf_c >= 0.5 * nf and pfr < 0.12)
        P.mfrac = (o.bs_sum + 1.8) / (o.bs_n + 3.0)
        P.bsn = o.bs_n
        P.cont = (1.0 - g) * 0.22 + g * (1.0 - (o.fr_f + 4.5) / (o.fr_n + 6.0))
        o.prof = P
        return P

    # ========================================================================= hand context
    def _parse(self, state):
        n = len(state["stacks"])
        self.n = n
        c = _Ctx(n)
        bets = [0] * n
        contrib = [0] * n
        pot = 0
        cur = 0
        street = "preflop"
        R = 0
        thr = self.shove_thr
        start = self.start
        pre = True
        for e in state["history"]:
            a = e["action"]
            if e["street"] != street:
                street = e["street"]
                pre = False
                bets = [0] * n
                cur = 0
                c.chk = [0] * n
                c.prev_aggr = c.aggr
                c.aggr = -1
                c.prev_nb = c.st_nb
                c.st_nb = 0
            if a == "fold":
                continue
            s = e["seat"]
            amt = e.get("amount") or 0
            if a == "small_blind" or a == "big_blind":
                bets[s] = amt
                contrib[s] += amt
                pot += amt
                if amt > cur:
                    cur = amt
                continue
            if pre:
                if a == "raise":
                    R += 1
                    c.pre_rl[s] = R
                    c.pre_last = s
                    c.aggr = s
                    add = amt - bets[s]
                    contrib[s] += add
                    pot += add
                    bets[s] = amt
                    cur = amt
                    if amt >= thr or contrib[s] >= start:
                        c.pre_sh[s] = 1
                elif a == "call":
                    if R == 0:
                        c.pre_limp[s] = 1
                        c.n_limp += 1
                    else:
                        c.pre_cl[s] = R
                        if cur >= thr:
                            c.pre_csh[s] = 1
                    contrib[s] += amt
                    pot += amt
                    bets[s] += amt
            elif a == "raise":
                add = amt - bets[s]
                c.nr[s] += 1
                if cur > 0:
                    c.rover[s] += 1
                c.lfrac[s] = add / pot if pot > 0 else 1.0
                contrib[s] += add
                pot += add
                bets[s] = amt
                cur = amt
                if contrib[s] >= start:
                    c.ai[s] = 1
                c.aggr = s
                c.st_nb += 1
            elif a == "call":
                c.ncl[s] += 1
                contrib[s] += amt
                pot += amt
                bets[s] += amt
            elif a == "check":
                c.chk[s] = 1
        c.R = R
        c.cur = cur
        return c

    # ========================================================================= layer 4: ranges
    def _pre_range(self, s, c):
        """Preflop action -> base range, with the exploit bridge's widths applied."""
        key = (s, c.pre_rl[s], c.pre_cl[s], c.pre_sh[s], c.pre_csh[s], c.pre_limp[s])
        r = self.prc.get(key)
        if r is not None:
            return r
        P = self._prof(s)
        g = P.g
        rl = c.pre_rl[s]
        cl = c.pre_cl[s]
        if rl and c.pre_sh[s]:
            prior = 0.06 if rl <= 1 else (0.045 if rl == 2 else 0.03)
            r = _range(0.0, (1.0 - g) * prior + g * P.psh, P.rb)
        elif rl:
            if rl == 1:
                n = self.n
                pos = (s - self.button) % n
                base = OPEN_SB if pos == 1 else (0.14 if pos == 2 else OPEN_FRAC[min((n - pos) % n, 6)])
                p = base * 1.15 * P.ratio
            elif rl == 2:
                p = P.p3
            else:
                p = P.p4
            p = _clamp(p, 0.015, 1.0)
            r = _range(min(0.02, p / 3.0), p, P.rb) if cl >= rl else _range(0.0, p, P.rb)
        elif c.pre_csh[s]:
            r = _range(0.0, P.pcsh, 0.0)
        elif cl:
            lo = min(P.p3 * 0.6, 0.06)
            r = _range(lo, lo + max(P.wcall if cl == 1 else 0.5 * P.wcall, 0.04), 0.0)
        elif c.pre_limp[s]:
            lo = _clamp(0.085 * P.ratio, 0.02, 0.5)
            r = _range(lo, max(lo + 0.12, (1.0 - g) * 0.45 + g * P.vpip), 0.0)
        else:                                       # big blind that checked its option
            r = _range(_clamp(0.085 * P.ratio, 0.02, 0.5), 1.0, 0.0)
        self.prc[key] = r
        return r

    def _post_q(self, s, c, P, wet):
        """Postflop narrowing: (top fraction of the range kept, weight of the rest, cap weight)."""
        nr = c.nr[s]
        nc = c.ncl[s]
        if nr == 0:
            if nc:
                q = P.cq ** nc
                return (q if q > 0.2 else 0.2), 0.3, 1.0
            return 1.0, 1.0, (0.6 if c.chk[s] else 1.0)
        ro = c.rover[s]
        L = nr + ro
        lf = c.lfrac[s]
        if L < 2 and lf >= max(0.95, 1.8 * P.mfrac) and (P.bsn >= 5 or lf >= 1.5):
            L = 2                                   # big-bet signal: far above their own average
        if c.ai[s] and lf >= 0.5:
            L = 3                                   # all-in: strongest tier
        qb, e = TIER[L if L < 3 else 3]
        q = qb * (P.ar if ro else P.ab) * (1.0 - 0.25 * wet)
        if nc:
            q *= P.cq ** (0.5 * nc)
        eps = e * P.epsm
        if P.passive and (ro or L >= 2):            # passive rocket
            q = min(q, 0.07)
            eps = 0.01
        return _clamp(q, 0.03, 1.0), _clamp(eps, 0.005, 0.9), 1.0

    def _vrange(self, st, s, c, q, eps, capw):
        key = (s, c.nr[s], c.ncl[s], c.rover[s], c.ai[s], c.chk[s], int(q * 500), int(eps * 200))
        r = st.rc.get(key)
        if r is not None:
            return r
        w = self._pre_range(s, c)[0]
        ws = [w[k] for k in st.cls_s]               # combos sorted weakest -> strongest
        cum = list(accumulate(ws))
        tot = cum[-1]
        if tot <= 1e-9:
            ws = [1.0] * len(ws)
            cum = list(accumulate(ws))
            tot = cum[-1]
        if q < 0.999:
            cut = bisect_left(cum, (1.0 - q) * tot)
            cut0 = bisect_left(cum, (1.0 - min(1.0, 1.4 * q)) * tot)
            mid = 0.5 * (1.0 + eps)
            ws = [x * eps for x in ws[:cut0]] + [x * mid for x in ws[cut0:cut]] + ws[cut:]
            cum = list(accumulate(ws))
        elif capw < 1.0:                            # checked: fewer of the very strong hands
            cut = bisect_left(cum, 0.85 * tot)
            ws = ws[:cut] + [x * capw for x in ws[cut:]]
            cum = list(accumulate(ws))
        r = (ws, cum)
        st.rc[key] = r
        return r

    def _setup(self, key, hole, board):
        st = _St()
        st.key = key
        st.rc = {}
        st.eqc = {}
        dead = 0
        for x in hole:
            dead |= BIT[x]
        brk = bsk = brm = 0
        bm = [0, 0, 0, 0]
        scnt = [0, 0, 0, 0]
        rcnt = [0] * 13
        for x in board:
            dead |= BIT[x]
            brk += RK[x]
            bsk += SK[x]
            r = x >> 2
            brm |= 1 << r
            bm[x & 3] |= 1 << r
            scnt[x & 3] += 1
            rcnt[r] += 1
        hm = bm[:]
        for x in hole:
            hm[x & 3] |= 1 << (x >> 2)
        st.brk = brk
        st.bsk = bsk
        st.bm = bm
        st.hm = hm
        st.hrk = brk + RK[hole[0]] + RK[hole[1]]
        st.hsk = bsk + SK[hole[0]] + SK[hole[1]]
        nb = len(board)
        st.need = 5 - nb
        st.deck = [x for x in range(52) if not dead & BIT[x]]
        CM = CMASK
        idx = [i for i in ALLI if not CM[i] & dead]
        NF = NOFLUSH
        mx = max(scnt)
        crk = CRK
        csk = CSK
        if mx >= 3:
            fs = scnt.index(mx)
            bms = bm[fs]
            csm = CSM[fs]
            FS = FSUIT
            FL = FLUSH
            vals = [FL[bms | csm[i]] if FS[bsk + csk[i]] >= 0 else NF[brk + crk[i]] for i in idx]
        else:
            vals = [NF[brk + crk[i]] for i in idx]
        hv = ev(board + hole)
        st.hv = hv
        # texture features (continuous): paired, monotone, connected, high card
        paired = 1.0 if max(rcnt) >= 2 else 0.0
        mono = ((0.0, 0.0, 0.45, 1.0), (0.0, 0.0, 0.35, 0.8, 1.0), (0.0, 0.0, 0.0, 0.6, 1.0, 1.0))[nb - 3][mx]
        mm = (brm << 1) | ((brm >> 12) & 1)
        best = 0
        for lo in range(10):
            k = bin((mm >> lo) & 31).count("1")
            if k > best:
                best = k
        if nb == 3:
            conn = 1.0 if best >= 3 else (0.3 if best == 2 else 0.0)
        else:
            conn = 1.0 if best >= 4 else (0.6 if best == 3 else (0.2 if best == 2 else 0.0))
        rs = sorted((x >> 2 for x in board), reverse=True)
        high = _clamp((rs[0] - 6) / 6.0, 0.0, 1.0)
        st.paired = paired
        st.wet = min(1.0, 0.6 * mono + 0.6 * conn)
        st.cb = _clamp(0.58 + 0.12 * paired + 0.14 * high - 0.25 * mono - 0.22 * conn, 0.12, 0.85)
        if nb < 5:
            # draws are ranked as if they were made hands of comparable value
            top, mid, low = rs[0], rs[1], rs[-1]
            if nb == 3:
                dv = (0, (1 << 20) | (low << 16), (1 << 20) | (mid << 16) | 0xFFFF, (1 << 20) | (top << 16),
                      (2 << 20) - 1, (2 << 20) - 1)
            else:
                dv = (0, 0, (1 << 20) | (low << 16), (1 << 20) | (mid << 16),
                      (1 << 20) | (mid << 16) | 0xFFFF, (1 << 20) | (top << 16))
            fd = FD4
            sd = SDR
            crm = CRM
            sc = [max(v, dv[fd[bsk + csk[i]] + sd[brm | crm[i]]]) for v, i in zip(vals, idx)]
            hi = CCIDX[hole[0] * 52 + hole[1]]
            hsc = max(hv, dv[fd[bsk + csk[hi]] + sd[brm | crm[hi]]])
        else:
            sc = vals
            hsc = hv
        order = sorted(range(len(idx)), key=sc.__getitem__)
        st.idx_s = [idx[k] for k in order]
        ccls = CCLS
        st.cls_s = [ccls[i] for i in st.idx_s]
        st.vals_s = [vals[k] for k in order]
        st.sc_s = [sc[k] for k in order]
        st.hsc = hsc
        n = len(order)
        st.hpct = (bisect_left(st.sc_s, hsc) + bisect_right(st.sc_s, hsc)) / (2.0 * n)
        self.st = st
        return st

    def _equity(self, st, vr, deadline, N):
        """Equity vs sampled villain ranges; exact enumeration on the river."""
        if st.need == 0:
            hv = st.hv
            vs = st.vals_s
            lo = bisect_left(vs, hv)
            hi = bisect_right(vs, hv)
            eq = 1.0
            for ws, cum in vr:
                tot = cum[-1]
                w = cum[lo - 1] if lo else 0.0
                t = (cum[hi - 1] if hi else 0.0) - w
                eq *= (w + 0.5 * t) / tot
            return eq
        rng = self.rng
        ch = rng.choices
        deck = st.deck
        xs = ch(deck, k=N)
        ys = ch(deck, k=N) if st.need == 2 else [52] * N
        idx_s = st.idx_s
        hrk = st.hrk
        hsk = st.hsk
        brk = st.brk
        bsk = st.bsk
        hm = st.hm
        bm = st.bm
        NF = NOFLUSH
        FS = FSUIT
        FL = FLUSH
        rk = RK
        sk = SK
        bit = BIT
        sbit = SBIT
        cmask = CMASK
        crk = CRK
        csk = CSK
        csm = CSM
        wins = 0.0
        cnt = 0
        if len(vr) == 1:
            s1 = ch(idx_s, cum_weights=vr[0][1], k=N)
            for it in range(N):
                x = xs[it]
                y = ys[it]
                i = s1[it]
                if x == y or cmask[i] & (bit[x] | bit[y]):
                    continue
                r2 = rk[x] + rk[y]
                s2 = sk[x] + sk[y]
                f = FS[hsk + s2]
                if f < 0:
                    hv = NF[hrk + r2]
                else:
                    hv = FL[hm[f] | sbit[f][x] | sbit[f][y]]
                f = FS[bsk + s2 + csk[i]]
                if f < 0:
                    vv = NF[brk + r2 + crk[i]]
                else:
                    vv = FL[bm[f] | sbit[f][x] | sbit[f][y] | csm[f][i]]
                if hv > vv:
                    wins += 1.0
                elif hv == vv:
                    wins += 0.5
                cnt += 1
                if not it & 63 and _pc() > deadline:
                    break
        else:
            samp = [ch(idx_s, cum_weights=v[1], k=N) for v in vr]
            for it in range(N):
                x = xs[it]
                y = ys[it]
                if x == y:
                    continue
                used = bit[x] | bit[y]
                r2 = rk[x] + rk[y]
                s2 = sk[x] + sk[y]
                best = -1
                ok = True
                for sv in samp:
                    i = sv[it]
                    m = cmask[i]
                    if m & used:
                        ok = False
                        break
                    used |= m
                    f = FS[bsk + s2 + csk[i]]
                    if f < 0:
                        vv = NF[brk + r2 + crk[i]]
                    else:
                        vv = FL[bm[f] | sbit[f][x] | sbit[f][y] | csm[f][i]]
                    if vv > best:
                        best = vv
                if not ok:
                    continue
                f = FS[hsk + s2]
                if f < 0:
                    hv = NF[hrk + r2]
                else:
                    hv = FL[hm[f] | sbit[f][x] | sbit[f][y]]
                if hv > best:
                    wins += 1.0
                elif hv == best:
                    wins += 0.5
                cnt += 1
                if not it & 31 and _pc() > deadline:
                    break
        if cnt < 8:
            return st.hpct ** len(vr)
        return wins / cnt

    # ========================================================================= layer 1: decisions
    def _act(self, state, t0):
        hn = state["hand_number"]
        if hn != self.prc_hand:
            self.prc_hand = hn
            self.prc = {}
            self.st = None
        self.seat = state["seat"]
        self.button = state["button"]
        c = self._parse(state)
        hole = [CARD[x] for x in state["hole_cards"]]
        board = [CARD[x] for x in state["board"]]
        if not board:
            return self._preflop(state, c, hole)
        return self._postflop(state, c, hole, board, t0)

    def _pf_eq(self, h, r):
        return sum(map(mul, PF_EQ[h], r[1])) / r[2]

    def _preflop(self, state, c, hole):
        me = self.seat
        n = self.n
        bb = state["big_blind"]
        pot = state["pot"]
        tc = state["to_call"]
        legal = state["legal_actions"]
        can_raise = "raise" in legal
        folded = state["folded"]
        stacks = state["stacks"]
        bets = state["bets"]
        h = _cls(hole[0], hole[1])
        pct = PF_PCT[h]
        pos = (me - self.button) % n
        dist = (n - pos) % n
        start = self.start
        R = c.R
        if R == 0:
            limp = c.n_limp
            bbseat = (self.button + 2) % n
            # who may continue and with what range (bridge input): limpers are in already,
            # players behind continue with their measured frequency
            fe = fep = 1.0
            wsum = esum = 0.0
            for s in range(n):
                if s == me or folded[s]:
                    continue
                P = self._prof(s)
                if c.pre_limp[s]:
                    r = self._pre_range(s, c)
                    wgt = 1.0
                else:
                    isbb = s == bbseat
                    wgt = min(0.95, P.cont * (1.5 if isbb else 1.0))
                    fe *= 1.0 - wgt
                    fep *= 1.0 - (0.33 if isbb else 0.22)
                    lo = min(P.p3 * 0.6, 0.06)
                    r = _range(lo, lo + max(P.wcall, 0.04), 0.0)
                wsum += wgt
                esum += wgt * self._pf_eq(h, r)
            eqv = esum / wsum if wsum > 0 else 0.5
            k = max(1, sum(1 for s in range(n) if s != me and not folded[s]))
            loose = wsum / k
            size = (2.5 + limp + (0.5 if pos == 1 else 0.0)) * (1.0 + 1.2 * max(0.0, loose - 0.3))
            if limp:
                size += 1.0
            amount = int(bb * min(size, 12.0))
            if can_raise and wsum >= 0.7 and eqv >= T_OPEN_VALUE + 0.02 * max(0.0, wsum - 1.0):
                return {"action": "raise", "amount": amount}       # value: ahead of what continues
            if pos == 2:
                return {"action": "check"}
            frac = OPEN_SB if pos == 1 else OPEN_FRAC[dist if dist < 7 else 6]
            if limp == 0:
                mult = _clamp(fe / fep, 0.75, 2.2) if fep > 0 else 1.0
                steal = fe * 1.5 * bb > (1.0 - fe) * amount * 0.75 + 2.0   # any-two steal is +EV
                if can_raise and (pct <= min(0.9, frac * mult) or steal):
                    return {"action": "raise", "amount": amount}
                return {"action": "fold"}
            if can_raise and pct <= min(frac, 0.30) * 0.6:
                return {"action": "raise", "amount": amount}
            if (pos <= 1 or dist <= 2) and pct <= 0.5 and (PF_PLAY[h] or pct <= 0.25) and tc <= bb:
                return {"action": "call"}
            return {"action": "fold"}
        # ---- facing a raise: equity vs the raiser's adjusted range against fixed thresholds
        v = c.pre_last
        if v < 0 or v == me or folded[v]:
            v = -1
            for s in range(n):
                if s != me and not folded[s] and (v < 0 or c.pre_rl[s] > c.pre_rl[v]):
                    v = s
        eq = self._pf_eq(h, self._pre_range(v, c))
        nother = 0
        for s in range(n):
            if s != me and s != v and not folded[s] and (c.pre_cl[s] or c.pre_rl[s]):
                e2 = self._pf_eq(h, self._pre_range(s, c))
                eq *= min(1.0, e2 ** 0.85 + 0.06)
                nother += 1
        po = tc / float(pot + tc)
        risk = tc / float(start)
        pen = VAR_C * risk * risk if risk > 0.10 else 0.0
        mystack = stacks[me]
        if tc >= 0.35 * start or tc >= mystack or (c.pre_sh[v] and tc >= 0.25 * start):
            # facing a shove: pure pot odds + variance penalty
            if eq >= po + pen + 0.01:
                return {"action": "call"}
            return {"action": "fold"}
        cur = c.cur
        # who acts after us postflop? in position if no live opponent sits between us and the button
        myo = (me - self.button - 1) % n
        ip = all(folded[s] or s == me or (s - self.button - 1) % n < myo for s in range(n))
        if can_raise and eq >= T_PRE_VALUE + (0.03 if nother else 0.0):
            to = int(cur * (3.0 if ip else 3.6)) + nother * cur
            if to >= 0.4 * start:
                return {"action": "all_in"} if eq >= T_PRE_VALUE + 0.04 else {"action": "call"}
            return {"action": "raise", "amount": to}
        rz = (0.92 if ip else 0.80) * (0.92 if R >= 2 else 1.0)
        play = 0.0
        if tc <= 0.08 * start:
            i, j = divmod(h, 13)
            if i == j:
                play = 0.03
            elif PF_PLAY[h]:
                play = 0.02
            elif i > j and i - j >= 4:
                play = -0.02
        need = po / rz + 0.02 + pen
        if tc > 0.12 * start:
            need = max(need, po + 0.08)
        if eq + play >= need:
            return {"action": "call"}
        return {"action": "fold"}

    def _postflop(self, state, c, hole, board, t0):
        me = self.seat
        n = self.n
        folded = state["folded"]
        stacks = state["stacks"]
        bets = state["bets"]
        pot = state["pot"]
        tc = state["to_call"]
        legal = state["legal_actions"]
        can_raise = "raise" in legal
        button = self.button
        opps = [s for s in range(n) if s != me and not folded[s]]
        if not opps:
            return {"action": "check"} if tc == 0 else {"action": "call"}
        nb = len(board)
        key = (state["hand_number"], nb)
        st = self.st
        if st is None or st.key != key:
            st = self._setup(key, hole, board)
        nv = len(opps)
        # ---- layer 3 + 4: adjusted ranges, then equity
        vinfo = []
        for s in opps:
            P = self._prof(s)
            q, eps, capw = self._post_q(s, c, P, st.wet)
            vinfo.append((q, s, eps, capw, P))
        vinfo.sort(key=lambda t: t[0])
        use = vinfo[:3]
        spent = self.spent
        if spent > 7.5:                                    # time bank nearly gone: table-only play
            eq = st.hpct ** nv
        else:
            vr = [self._vrange(st, s, c, q, eps, capw) for q, s, eps, capw, P in use]
            ek = tuple(id(r) for r in vr)
            eq = st.eqc.get(ek)
            if eq is None:
                N = (0, 560, 360, 250)[len(vr)]
                if spent > 4.0:
                    N = N // 2 if spent < 6.0 else N // 4
                eq = self._equity(st, vr, t0 + 0.0022, N)
                st.eqc[ek] = eq
            if nv > 3:
                eq *= 0.9 ** (nv - 3)
        # ---- layer 1: fixed thresholds on equity
        mystack = stacks[me]
        mybet = bets[me]
        myo = (me - button - 1) % n
        ip = all((s - button - 1) % n < myo for s in opps)
        effv = max(stacks[s] + bets[s] for s in opps)
        eff = min(mystack + mybet, effv)
        spr = (eff - mybet - tc) / float(pot + tc) if pot + tc > 0 else 10.0
        if spr < 0:
            spr = 0.0
        t_commit = 0.50 + 0.22 / (1.0 + math.exp(-(spr - 4.0) / 1.5))   # SPR sigmoid
        river = nb == 5
        rnd = self.rng.random()
        # opponent-aware sizing input: how often do these villains call a medium bet?
        callp = 1.0
        for q, s, eps, capw, P in use:
            callp *= P.fold[1]
        callp = 1.0 - callp ** (1.0 / len(use))            # mean call propensity
        if tc == 0:
            if not can_raise:
                return {"action": "check"}
            lo = state["min_raise_to"]
            mw = MW[nv]
            if eq >= T_VALUE * mw:
                frac = (0.8 if river else 0.7) if ip else 0.75
                if callp > 0.88:
                    frac = 1.25                            # confirmed stations: overbet for value
                elif callp > 0.72:
                    frac *= 1.35                           # stations pay: bet bigger
                elif callp < 0.45:
                    frac *= 0.8
                return self._bet(state, pot, frac, eq, t_commit, mystack, mybet)
            init = c.prev_aggr == me
            thin = (T_THIN if ip else T_THIN_OOP) * mw
            if river:
                thin += 0.04
            if eq >= thin:
                frac = 0.5 if callp < 0.72 else 0.66
                amt = int(pot * frac)
                if amt <= 0.33 * mystack:
                    return {"action": "raise", "amount": mybet + max(amt, lo)}
                return {"action": "check"}
            # bluffs: c-bet / barrel by texture, rare steal; fold equity comes from the model
            if nv <= 2:
                frac = 0.66 if river else (0.4 if st.wet < 0.4 else 0.6)
                po_v = frac / (1.0 + 2.0 * frac)
                b = 0 if po_v < 0.22 else (1 if po_v < 0.31 else 2)
                fe = 1.0
                for q, s, eps, capw, P in use:
                    f = P.fold[b]
                    if c.nr[s]:
                        f *= 0.5
                    fe *= f
                freq = 0.0
                if init:
                    freq = st.cb * (1.0 if nb == 3 else (0.7 if nb == 4 else 0.45))
                elif ip and nb >= 4 and c.prev_nb == 0 and c.st_nb == 0:
                    freq = 0.33                            # rare steal after two streets of checks
                freq *= min(1.6, fe / 0.42)
                if nv == 2:
                    freq *= 0.45
                if not river and eq >= 0.33:
                    freq *= 1.25
                if river and eq >= 0.32:
                    freq = 0.0                             # showdown value: do not turn it into a bluff
                need = frac / (1.0 + frac) - 0.4 * eq
                if freq > 0.0 and fe >= need and rnd < freq:
                    amt = max(int(pot * frac), lo)
                    if amt <= 0.3 * mystack:
                        return {"action": "raise", "amount": mybet + amt}
            return {"action": "check"}
        # ---- facing a bet
        po = tc / float(pot + tc)
        risk = tc / float(self.start)
        pen = VAR_C * risk * risk if risk > 0.10 else 0.0
        sig = 1.0 / (1.0 + math.exp(-(spr - 4.0) / 1.5))
        pen += 0.06 * risk * sig                            # high SPR: demand more to stack off
        allin_call = tc >= mystack
        if can_raise and not allin_call and eq >= (T_VALUE + 0.04 if river else T_VALUE) \
                and (nv == 1 or eq >= 0.82):
            to = mybet + tc + int(0.75 * (pot + tc))
            if to >= 0.55 * (mystack + mybet):
                if eq >= max(t_commit, T_VALUE):
                    return {"action": "all_in"}
                return {"action": "call"}
            return {"action": "raise", "amount": to}
        if river:
            req = po + 0.02 + pen
            if eq >= req:
                return {"action": "call"}
            # near-MDF defence with bluff catchers so that we are not auto-bluffable
            mdf = (pot - tc) / float(pot) if pot > 0 else 0.5
            if eq >= po - 0.05 and st.hpct >= 1.0 - 0.5 * mdf and risk <= 0.35:
                return {"action": "call"}
            return {"action": "fold"}
        m = (0.06 if nb == 3 else 0.05) + (0.0 if ip else 0.02)
        req = max(po + m, T_CALL * math.sqrt(po / 0.3333)) + pen
        if allin_call:
            req = po + 0.02 + pen
        if eq >= req:
            return {"action": "call"}
        return {"action": "fold"}

    def _bet(self, state, pot, frac, eq, t_commit, mystack, mybet):
        lo = state["min_raise_to"]
        amt = int(pot * frac)
        if amt >= 0.6 * mystack:                           # the bet commits us: SPR-aware
            if eq >= t_commit:
                return {"action": "all_in"}
            amt = int(0.33 * mystack)
        to = mybet + amt
        return {"action": "raise", "amount": to if to > lo else lo}


CCIDX = {}
for _i in range(1326):
    CCIDX[CA[_i] * 52 + CB[_i]] = _i
    CCIDX[CB[_i] * 52 + CA[_i]] = _i

try:
    gc.collect()
    gc.freeze()
except Exception:
    pass
