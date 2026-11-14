"""GrandSlam-H: GrandSlam decision content + Hyperion exploit bridge.

Four layers (never alter the core logic, alter its inputs):
  1. Decision engine: GrandSlam preflop charts + postflop mixed-strategy tables,
     keyed by an *equity tier* (fixed thresholds), texture, draw, SPR, position.
  2. Opponent model: per-seat Beta-shrunk frequencies learned in on_hand_end.
  3. Exploit bridge: turns those frequencies into villain ranges (top-p of hands
     for the action they took), gated 20 -> 60 observed actions. Only ranges and
     fold-equity inputs change; tables and thresholds never do.
  4. Range-aware equity: PF_EQ preflop, exact enumeration on the river, Monte
     Carlo on flop/turn, all against the adjusted ranges.
Stdlib only, single file, built for a 10 ms decision clock.
"""
import base64
import gc
import random
import time
import zlib
from bisect import bisect_left, bisect_right
from itertools import accumulate, combinations_with_replacement
from math import exp
from operator import mul

_pc = time.perf_counter
RANKS = "23456789TJQKA"
SUITS = "cdhs"
CARD = {r + s: ri * 4 + si for ri, r in enumerate(RANKS) for si, s in enumerate(SUITS)}
RK = [5 ** (c >> 2) for c in range(52)]          # rank key: sum is unique per rank multiset
SK = [8 ** (c & 3) for c in range(52)]           # suit key: 3-bit counter per suit
BIT = [1 << c for c in range(52)]
SBIT = [[(1 << (c >> 2)) if (c & 3) == s else 0 for c in range(52)] for s in range(4)]


def _straight_high(mask):
    m = (mask << 1) | (1 if mask & 4096 else 0)
    for top in range(13, 3, -1):
        if (m >> (top - 4)) & 31 == 31:
            return top - 1
    return -1


ST = [_straight_high(m) for m in range(8192)]    # straight high card per 13-bit rank mask
FL = [0] * 8192                                  # flush / straight-flush strength per suit rank mask
for _m in range(8192):
    if bin(_m).count("1") >= 5:
        if ST[_m] >= 0:
            FL[_m] = (8 << 20) | (ST[_m] << 16)
        else:
            _r = [r for r in range(12, -1, -1) if (_m >> r) & 1]
            FL[_m] = (5 << 20) | (_r[0] << 16) | (_r[1] << 12) | (_r[2] << 8) | (_r[3] << 4) | _r[4]
FS = [-1] * 4096                                 # suit holding >= 5 cards, from the suit key
for _i in range(4096):
    for _s in range(4):
        if (_i >> (3 * _s)) & 7 >= 5:
            FS[_i] = _s
NF = {}                                          # non-flush strength for every 5/6/7-card rank multiset


def _build_nf():
    p5 = [5 ** r for r in range(13)]
    for n in (5, 6, 7):
        for t in combinations_with_replacement(range(13), n):
            cnt = [0] * 13
            key = 0
            mask = 0
            for r in t:
                cnt[r] += 1
                key += p5[r]
                mask |= 1 << r
            q = tr = None
            pr = []
            sg = []
            bad = False
            for r in range(12, -1, -1):
                c = cnt[r]
                if c == 1:
                    sg.append(r)
                elif c == 2:
                    pr.append(r)
                elif c == 3:
                    if tr is None:
                        tr = r
                    else:
                        pr.append(r)          # second trips plays as the pair
                elif c == 4:
                    if q is None:
                        q = r
                elif c > 4:
                    bad = True
            if bad:
                continue
            if q is not None:
                k = max(r for r in range(13) if cnt[r] and r != q)
                v = (7 << 20) | (q << 16) | (k << 12)
            elif tr is not None and pr:
                v = (6 << 20) | (tr << 16) | (max(pr) << 12)
            else:
                sh = ST[mask]
                if sh >= 0:
                    v = (4 << 20) | (sh << 16)
                elif tr is not None:
                    v = (3 << 20) | (tr << 16) | (sg[0] << 12) | (sg[1] << 8)
                elif len(pr) >= 2:
                    rest = max(r for r in range(13) if cnt[r] and r != pr[0] and r != pr[1])
                    v = (2 << 20) | (pr[0] << 16) | (pr[1] << 12) | (rest << 8)
                elif pr:
                    v = (1 << 20) | (pr[0] << 16) | (sg[0] << 12) | (sg[1] << 8) | (sg[2] << 4)
                else:
                    v = (sg[0] << 16) | (sg[1] << 12) | (sg[2] << 8) | (sg[3] << 4) | sg[4]
            NF[key] = v


_build_nf()


def ev(cards):
    """Strength of the best 5-card hand from 5-7 int cards (same ordering as the engine)."""
    k = 0
    s = 0
    for c in cards:
        k += RK[c]
        s += SK[c]
    f = FS[s]
    if f < 0:
        return NF[k]
    m = 0
    for c in cards:
        if c & 3 == f:
            m |= 1 << (c >> 2)
    return FL[m]


# ---- the 1326 two-card combos ----
CRK = []
CSK = []
CM = []
CSM = [[], [], [], []]
CCLS = []
CIDX = [0] * 2704
for _a in range(52):
    for _b in range(_a + 1, 52):
        CIDX[_a * 52 + _b] = CIDX[_b * 52 + _a] = len(CRK)
        CRK.append(RK[_a] + RK[_b])
        CSK.append(SK[_a] + SK[_b])
        CM.append(BIT[_a] | BIT[_b])
        for _s in range(4):
            CSM[_s].append(SBIT[_s][_a] | SBIT[_s][_b])
        _i = 12 - (_b >> 2)
        _j = 12 - (_a >> 2)
        CCLS.append(_i * 13 + _i if _i == _j else (_i * 13 + _j if (_a & 3) == (_b & 3) else _j * 13 + _i))
ALLC = list(range(1326))

# ---- preflop equity data (169x169, shared/preflop_data.py) ----
_R = "AKQJT98765432"
PF_NAMES = []
for _i in range(13):
    for _j in range(13):
        PF_NAMES.append(_R[_i] * 2 if _i == _j else (_R[_i] + _R[_j] + "s" if _i < _j else _R[_j] + _R[_i] + "o"))
PF_INDEX = {n: k for k, n in enumerate(PF_NAMES)}
PF_COMBOS = [6 if len(n) == 2 else (4 if n[2] == "s" else 12) for n in PF_NAMES]
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
PF_VS_RANDOM = [sum(PF_EQ[a][b] * PF_COMBOS[b] for b in range(169)) / 1326.0 for a in range(169)]


def _rank_score(c):
    i, j = divmod(c, 13)
    s = PF_VS_RANDOM[c]
    if i < j:
        s += 0.012 + (0.012 if j - i <= 2 else 0.0)   # suited / connected play better than raw equity
    return s


ORDER = sorted(range(169), key=_rank_score, reverse=True)
POSF = [0.0] * 169                               # midpoint percentile of each class (0 = best)
_c = 0.0
for _k in ORDER:
    POSF[_k] = (_c + PF_COMBOS[_k] * 0.5) / 1326.0
    _c += PF_COMBOS[_k]
_RC = {}


def top_range(p):
    """Soft top-p range: (class weights, weights*combos, total). Cached on a 1% grid."""
    q = int(p * 100 + 0.5)
    if q < 1:
        q = 1
    if q > 100:
        q = 100
    r = _RC.get(q)
    if r is None:
        pp = q / 100.0
        w = [1.0 if pp >= 0.99 else max(0.0, min(1.0, (pp * 1.25 - POSF[c]) / (0.5 * pp))) for c in range(169)]
        wc = [w[c] * PF_COMBOS[c] for c in range(169)]
        r = _RC[q] = (w, wc, sum(wc) or 1.0)
    return r


def band_range(hi, lo, damp):
    """Top-hi range with its top-lo part damped (the hands that would have raised instead)."""
    key = (int(hi * 100 + 0.5), int(lo * 100 + 0.5), int(damp * 10))
    r = _RC.get(key)
    if r is None:
        a = top_range(hi)[0]
        b = top_range(lo)[0]
        w = [x * (1.0 - (1.0 - damp) * y) for x, y in zip(a, b)]
        wc = [w[c] * PF_COMBOS[c] for c in range(169)]
        r = _RC[key] = (w, wc, sum(wc) or 1.0)
    return r


def eqvs(cls, rng):
    return sum(map(mul, PF_EQ[cls], rng[1])) / rng[2]


# ---- GrandSlam preflop charts (6-max) extended with two tighter early seats ----
def _expand(tok):
    plus = tok.endswith("+")
    core = tok[:-1] if plus else tok
    out = []
    if len(core) == 2 and core[0] == core[1]:
        lo = RANKS.index(core[0])
        for v in range(lo, 13 if plus else lo + 1):
            out.append(RANKS[v] * 2)
    elif len(core) == 3:
        hv, lv = RANKS.index(core[0]), RANKS.index(core[1])
        if hv < lv:
            hv, lv = lv, hv
        for k in (range(lv, hv) if plus else (lv,)):
            out.append(RANKS[hv] + RANKS[k] + core[2])
    return out


def RS(s):
    out = set()
    for tok in s.replace(",", " ").split():
        for name in _expand(tok):
            out.add(PF_INDEX[name])
    return frozenset(out)


OPEN = {
    "U0": RS("55+, ATs+, KJs+, QJs, JTs, AQo+"),
    "U1": RS("44+, ATs+, KTs+, QJs, JTs, T9s, AJo+, KQo"),
    "LJ": RS("22+, ATs+, KTs+, QTs+, JTs, T9s, AJo+, KQo"),
    "HJ": RS("22+, A9s+, A5s, KTs+, Q9s+, J9s+, T9s, 98s, ATo+, KJo+, QJo"),
    "CO": RS("22+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, A9o+, A5o, KTo+, QTo+, JTo"),
    "BTN": RS("22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, A2o+, K9o+, Q9o+, J9o+, T9o"),
    "SB": RS("22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 76s, 65s, A7o+, A5o, K9o+, Q9o+, JTo"),
    "BB": RS("55+, A8s+, KTs+, QTs+, JTs, T9s, ATo+, KQo"),
}
OPENF = {k: sum(PF_COMBOS[c] for c in v) / 1326.0 for k, v in OPEN.items()}
OPENF["BB"] = 0.30
TIGHTER = {"U0": "U0", "U1": "U0", "LJ": "U1", "HJ": "LJ", "CO": "HJ", "BTN": "CO", "SB": "CO", "BB": "BB"}
V3 = {
    "U0": RS("QQ+, AKs, AKo"), "U1": RS("QQ+, AKs, AKo"), "LJ": RS("QQ+, AKs, AKo"),
    "HJ": RS("JJ+, AKs, AKo"), "CO": RS("JJ+, AQs+, AKo"), "BTN": RS("TT+, AQs+, AKo"),
    "SB": RS("QQ+, AKs, AKo"), "BB": RS("QQ+, AKs, AKo"),
}
B3 = RS("A5s, A4s, KQs")                         # light 3-bets, mixed
V4 = RS("QQ+, AKs, AKo")
PREMIUM = RS("JJ+, AKs, AKo")
LIMP_BEHIND = RS("22+, A2s+, K9s+, Q9s+, J9s+, T8s+, 97s+, 86s+, 75s+, 64s+, 54s, ATo+, KJo+, QJo")


def _posname(rel, n):
    if rel == 0:
        return "BTN"
    if rel == 1:
        return "SB"
    if rel == 2:
        return "BB"
    k = n - rel
    return "CO" if k == 1 else "HJ" if k == 2 else "LJ" if k == 3 else "U1" if k == 4 else "U0"


def _play(cls, ip, multi, cheap):
    """Equity-realisation factor of a class (playability), position and multiway aware."""
    i, j = divmod(cls, 13)
    if i == j:
        r = 1.22 if (cheap and i >= 4) else 1.0     # cheap set-mining
        if multi:
            r *= 1.04
    elif i < j:
        r = 0.92 if i == 0 else (0.95 if j - i <= 2 else 0.86)
        if multi:
            r *= 1.05
    else:
        r = 0.80 if i <= 4 else (0.70 if j == 0 else 0.62)
        if multi:
            r *= 0.90
    return r * 1.05 if ip else r


# ---- postflop features (GrandSlam ports on int cards) ----
AIR, WSD, THIRD, SECOND, WTP, STP, OVERP, TWOP, TRIPS, STRT, FLSH, FULL = range(12)


def hs_bucket(c1, c2, board, strength):
    cat = strength >> 20
    if cat >= 6:
        return FULL
    if cat >= 2:
        return (TWOP, TRIPS, STRT, FLSH)[cat - 2]
    r1, r2 = c1 >> 2, c2 >> 2
    br = [c >> 2 for c in board]
    top = max(br)
    if cat == 1:
        if r1 == r2:
            return OVERP if r1 > top else THIRD
        paired = r1 if r1 in br else (r2 if r2 in br else -1)
        if paired < 0:
            return WSD
        kick = r2 if paired == r1 else r1
        bv = sorted(set(br), reverse=True)
        idx = bv.index(paired)
        if idx == 0:
            return STP if kick >= 8 else WTP
        return SECOND if idx == 1 else THIRD
    if (r1 > top and r2 > top) or r1 == 12 or r2 == 12:
        return WSD
    return AIR


def texture(board):
    vals = [c >> 2 for c in board]
    sc = [0, 0, 0, 0]
    mask = 0
    for c in board:
        sc[c & 3] += 1
        mask |= 1 << (c >> 2)
    ms = max(sc)
    dist = sorted(set(vals))
    top = dist[-1]
    if len(board) >= 4 and ST[mask] >= 0:
        return "draw_completed"
    if ms >= 3:
        return "monotone"
    if len(dist) != len(vals):
        return "paired"
    conn = len(dist) >= 3 and dist[-1] - dist[0] <= 4
    if conn and dist[0] >= 8:
        return "broadway_connected"
    if conn and top <= 7:
        return "low_connected"
    if conn:
        return "connected"
    if ms == 2:
        return "two_tone"
    if top == 12:
        return "A_high_dry"
    if top == 11:
        return "K_high_dry"
    return "disconnected_low"


DRY = ("A_high_dry", "K_high_dry", "disconnected_low")
WET = ("monotone", "broadway_connected", "low_connected", "connected", "draw_completed")
FE_TEX = {"A_high_dry": 0.05, "K_high_dry": 0.04, "disconnected_low": 0.03, "paired": 0.05,
          "two_tone": -0.02, "monotone": -0.02, "connected": -0.05, "low_connected": -0.05,
          "broadway_connected": -0.06, "draw_completed": -0.03}


def _comps(mask):
    if ST[mask] >= 0:
        return 0
    n = 0
    for d in range(13):
        if not (mask >> d) & 1 and ST[mask | (1 << d)] >= 0:
            n += 1
    return n


def draw_bucket(c1, c2, board):
    """0 none, 1 backdoor, 2 gutshot, 3 OESD, 4 flush draw, 5 nut flush draw, 6 combo."""
    if len(board) >= 5:
        return 0
    sc = [0, 0, 0, 0]
    bm = 0
    for c in board:
        sc[c & 3] += 1
        bm |= 1 << (c >> 2)
    s1, s2 = c1 & 3, c2 & 3
    sc[s1] += 1
    sc[s2] += 1
    f4 = -1
    for s in (s1, s2):
        if sc[s] == 4:
            f4 = s
    nut = f4 >= 0 and (c1 == 48 + f4 or c2 == 48 + f4)
    hm = bm | (1 << (c1 >> 2)) | (1 << (c2 >> 2))
    ca = _comps(hm)
    cb = _comps(bm)
    oesd = ca >= 2 and ca > cb
    gut = ca == 1 and ca > cb
    if f4 >= 0 and (oesd or gut):
        return 6
    if nut:
        return 5
    if f4 >= 0:
        return 4
    if oesd:
        return 3
    if gut:
        return 2
    if len(board) == 3 and (sc[s1] == 3 or sc[s2] == 3):
        return 1
    return 0


def spr_bucket(stack, pot):
    if pot <= 0:
        return 3
    s = stack / pot
    return 0 if s < 1 else 1 if s < 3 else 2 if s < 6 else 3 if s < 10 else 4


def _norm(d):
    tot = 0.0
    for v in d.values():
        if v > 0:
            tot += v
    if tot <= 0:
        return {"check": 1.0} if "check" in d else {"fold": 1.0}
    return {k: v / tot for k, v in d.items() if v > 0}


def strat_checked(t, tex, draw, sprb, pos):
    """GrandSlam checked-to table. t = equity tier 0..4, pos 0 OOP / 1 IP / 2 sandwiched."""
    ip = pos == 1
    if t == 4:
        if sprb == 0:
            d = {"all_in": 0.35, "bet_100": 0.35, "bet_66": 0.2, "check": 0.1}
        else:
            d = {"bet_66": 0.5, "bet_100": 0.25, "bet_33": 0.1, "check": 0.15}
    elif t == 3:
        d = {"bet_66": 0.5, "bet_33": 0.2, "check": 0.3}
    elif t == 2:
        d = {"bet_33": 0.35, "check": 0.65}
    elif draw >= 3:
        d = {"bet_66": 0.5, "bet_33": 0.1, "check": 0.4} if ip else {"bet_66": 0.4, "check": 0.6}
    elif draw >= 1:
        d = {"bet_33": 0.25, "check": 0.75}
    elif t == 1:
        d = {"check": 0.9, "bet_33": 0.1}
    elif ip and tex in DRY:
        d = {"bet_66": 0.35, "bet_33": 0.1, "check": 0.55}
    else:
        d = {"bet_33": 0.18, "check": 0.82}
    if pos == 2:
        moved = 0.0
        for k in list(d):
            if k != "check":
                moved += d[k] * 0.6
                d[k] *= 0.4
        d["check"] = d.get("check", 0.0) + moved
    elif not ip:
        moved = 0.0
        for k in list(d):
            if k.startswith("bet"):
                moved += d[k] * 0.15
                d[k] *= 0.85
        d["check"] = d.get("check", 0.0) + moved
    return d


def strat_facing(t, draw, sprb, pos, pressure):
    """GrandSlam facing-bet table (pressure 0 small .. 3 overbet/raise)."""
    if t == 4:
        if sprb == 0 or pressure >= 2:
            d = {"all_in": 0.3, "raise_pot": 0.25, "call": 0.45}
        else:
            d = {"raise_pot": 0.4, "raise_value": 0.2, "call": 0.4}
    elif t == 3:
        fb = 0.12 * pressure
        d = {"call": max(0.0, 0.7 - fb), "raise_value": max(0.0, 0.15 - 0.03 * pressure), "fold": 0.15 + fb}
    elif t == 2:
        d = ({"call": 0.75, "fold": 0.2, "raise_value": 0.05}, {"call": 0.62, "fold": 0.38},
             {"call": 0.4, "fold": 0.6}, {"call": 0.18, "fold": 0.82})[pressure]
    elif draw >= 3:
        d = ({"call": 0.5, "raise_pot": 0.3, "fold": 0.2}, {"call": 0.6, "raise_pot": 0.1, "fold": 0.3},
             {"call": 0.5, "fold": 0.5}, {"call": 0.35, "fold": 0.65})[pressure]
    elif draw >= 1 or t == 1:
        d = ({"call": 0.45, "fold": 0.55}, {"call": 0.3, "fold": 0.7},
             {"call": 0.1, "fold": 0.9}, {"call": 0.1, "fold": 0.9})[pressure]
    else:
        d = {"fold": 1.0}
    d = dict(d)
    if pos == 2:
        if "raise_pot" in d:
            x = d.pop("raise_pot")
            d["call"] = d.get("call", 0.0) + x * 0.5
            d["fold"] = d.get("fold", 0.0) + x * 0.5
        if "raise_value" in d:
            d["call"] = d.get("call", 0.0) + d.pop("raise_value")
    return d


BLUFF_MULT = (1.0, 1.0, 0.30, 0.05, 0.02, 0.0)   # GrandSlam multiway bluff multipliers by n_opp
SIZE = {"bet_33": 0.33, "bet_66": 0.66, "bet_100": 1.0, "bet_150": 1.5}

# ---- opponent model: population priors ----
BETP = (0.42, 0.36, 0.33)        # bets when checked to, by street
FOLDP = (0.45, 0.40, 0.45)       # folds facing a bet, by street
RAISEP = (0.10, 0.08, 0.07)      # raises facing a bet, by street
SZP = (0.33, 0.45, 0.55)         # folds by bet size bucket (<0.45 pot, <0.9 pot, bigger)
SIDX = {"flop": 0, "turn": 1, "river": 2}


class Opp:
    __slots__ = ("n", "g", "hands", "vpip", "pfr", "jam", "fr_opp", "fr_fold", "fr_3b", "f3_opp", "f3_fold",
                 "rs_sum", "rs_n", "b_opp", "b_n", "fb_opp", "fb_fold", "fb_raise", "sz_opp", "sz_fold",
                 "bs_sum", "bs_n", "sd_agg", "sd_weak", "jsd_n", "jsd_sum", "pc_opp", "pc_n")

    def __init__(self):
        self.n = 0              # observed actions (drives the gate)
        self.g = 0.0            # gate: 0 below 20 actions, 1 from 60
        self.hands = 0
        self.vpip = self.pfr = self.jam = 0
        self.fr_opp = self.fr_fold = self.fr_3b = 0      # first decision facing one raise
        self.f3_opp = self.f3_fold = 0                   # raised, then faced a re-raise
        self.rs_sum = 0.0
        self.rs_n = 0                                    # open size in bb
        self.b_opp = [0, 0, 0]
        self.b_n = [0, 0, 0]
        self.fb_opp = [0, 0, 0]
        self.fb_fold = [0, 0, 0]
        self.fb_raise = [0, 0, 0]
        self.sz_opp = [0, 0, 0]
        self.sz_fold = [0, 0, 0]
        self.bs_sum = 0.0
        self.bs_n = 0
        self.sd_agg = self.sd_weak = 0                   # showed down after betting late; with air
        self.jsd_n = 0
        self.jsd_sum = 0.0                               # percentile of hands shown after a preflop jam
        self.pc_opp = self.pc_n = 0                      # faced a big preflop raise (>= 12 bb); called it

    def est(self, prior, k, n, w):
        """Beta posterior mean, moved from the prior only as far as the gate allows."""
        return prior + self.g * ((prior * w + k) / (w + n) - prior)

    def vpip_e(self):
        return self.est(0.28, self.vpip, self.hands, 10.0)

    def pfr_e(self):
        return self.est(0.16, self.pfr, self.hands, 10.0)

    def jam_e(self):
        return self.est(0.03, self.jam, self.hands, 12.0)

    def tb_e(self):
        return self.est(0.06, self.fr_3b, self.fr_opp, 10.0)

    def bet_e(self, t):
        return self.est(BETP[t], self.b_n[t], self.b_opp[t], 6.0)

    def fold_e(self, t):
        return self.est(FOLDP[t], self.fb_fold[t], self.fb_opp[t], 6.0)

    def raise_e(self, t):
        return self.est(RAISEP[t], self.fb_raise[t], self.fb_opp[t], 10.0)

    def szfold_d(self, b):
        return self.est(SZP[b], self.sz_fold[b], self.sz_opp[b], 6.0) - SZP[b]

    def bluff_e(self):
        return self.est(0.20, self.sd_weak, self.sd_agg, 6.0)

    def mean_bet(self):
        return (1.8 + self.bs_sum) / (3.0 + self.bs_n)

    def mean_open(self):
        return (8.4 + self.rs_sum) / (3.0 + self.rs_n)

    def kind(self):
        """Archetype label (used for the passive-rocket signal and river bluff-catch respect)."""
        if self.g < 0.25:
            return "unknown"
        if self.jam_e() >= 0.12:
            return "shover"
        v, p = self.vpip_e(), self.pfr_e()
        ra = (self.raise_e(0) + self.raise_e(1)) * 0.5
        fo = (self.fold_e(0) + self.fold_e(1)) * 0.5
        if p >= 0.40 or (self.bet_e(0) >= 0.65 and ra >= 0.22):
            return "maniac"
        if v >= 0.50 and fo <= 0.25:
            return "station"
        if ra <= 0.05 and fo <= 0.45 and v >= 0.25:
            return "passive"
        if v <= 0.14:
            return "nit"
        if v <= 0.30 and p >= 0.6 * v:
            return "tag"
        return "balanced"


def _keep_top(ws, f, fl):
    """Bet/raise: keep the top-f of the range (by strength), floor weight fl for the rest."""
    if f >= 0.97:
        return ws
    cum = list(accumulate(ws))
    tot = cum[-1]
    if tot <= 0:
        return ws
    b0 = (1.0 - 1.2 * f) * tot
    b1 = (1.0 - 0.8 * f) * tot
    if b0 < 0:
        b0 = 0.0
    k = (1.0 - fl) / (b1 - b0)
    return [x if c >= b1 else (x * fl if c <= b0 else x * (fl + k * (c - b0))) for x, c in zip(ws, cum)]


def _drop_bottom(ws, ff, flc, rf, damp):
    """Call: drop the bottom-ff (keeps floor flc for floats/draws), damp the top-rf (would have raised)."""
    cum = list(accumulate(ws))
    tot = cum[-1]
    if tot <= 0:
        return ws
    b0 = 0.8 * ff * tot
    b1 = 1.2 * ff * tot
    top = (1.0 - rf) * tot
    k = (1.0 - flc) / (b1 - b0) if b1 > b0 else 0.0
    return [(x * damp if c > top else x) if c >= b1 else (x * flc if c <= b0 else x * (flc + k * (c - b0)))
            for x, c in zip(ws, cum)]


def _damp_top(ws, f, damp):
    cum = list(accumulate(ws))
    tot = cum[-1]
    if tot <= 0:
        return ws
    top = (1.0 - f) * tot
    return [x * damp if c > top else x for x, c in zip(ws, cum)]


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _sig(x):
    return 1.0 / (1.0 + exp(-x))


class Agent:
    def __init__(self):
        self.seat = 0
        self.n = 8
        self.bb = 20
        self.stack0 = 2000
        self.opps = [Opp() for _ in range(10)]
        self.hn = -1
        self.spent = 0.0            # cumulative think time this round
        self.rng = random.Random(1)
        self.w = {}
        self.vdone = {}
        self.orders = {}
        self.wsc = {}
        self.tmax = 0.0
        self.errs = 0               # exceptions swallowed by act()/on_hand_end (should stay 0)

    def on_table_start(self, info):
        try:
            self.seat = int(info.get("seat", 0))
            self.n = int(info.get("num_players", 8))
            self.bb = int(info.get("big_blind", 20)) or 20
            self.stack0 = int(info.get("starting_stack", 2000)) or 2000
            while len(self.opps) < self.n:
                self.opps.append(Opp())
        except Exception:
            pass

    # ------------------------------------------------------------------ entry
    def act(self, state):
        t0 = _pc()
        try:
            a = self._act(state, t0)
        except Exception:
            a = None
            self.errs += 1
        if a is None:
            a = self._fallback(state)
        dt = _pc() - t0
        self.spent += dt
        if dt > self.tmax:
            self.tmax = dt
        return a

    def _fallback(self, st):
        try:
            legal = st.get("legal_actions") or []
            if "check" in legal:
                return {"action": "check"}
            tc = st.get("to_call") or 0
            if "call" in legal and tc * 8 <= (st.get("pot") or 0):
                return {"action": "call"}
        except Exception:
            pass
        return {"action": "fold"}

    def _legal(self, a, st, to_call, can_raise):
        legal = st["legal_actions"]
        k = a[0]
        if k == "r":
            if can_raise:
                lo = st["min_raise_to"]
                hi = st["max_raise_to"]
                amt = int(a[1])
                if amt >= 0.85 * hi and st.get("betting") == "no_limit":
                    amt = hi                      # do not leave crumbs behind
                return {"action": "raise", "amount": max(lo, min(amt, hi))}
            k = "c" if to_call > 0 else "k"
        if k == "c":
            if "call" in legal:
                return {"action": "call"}
            k = "k"
        if "check" in legal:
            return {"action": "check"}
        if k == "k" or k == "f":
            return {"action": "fold"}
        return {"action": "fold"}

    def _act(self, st, t0):
        seat = st["seat"]
        hole = st["hole_cards"]
        c1 = CARD[hole[0]]
        c2 = CARD[hole[1]]
        board = [CARD[x] for x in st["board"]]
        pot = st["pot"]
        to_call = st["to_call"]
        stacks = st["stacks"]
        folded = st["folded"]
        n = len(stacks)
        hist = st["history"]
        hn = st["hand_number"]
        if hn != self.hn:
            self.hn = hn
            self.w = {}
            self.vdone = {}
            self.orders = {}
            self.wsc = {}
        while len(self.opps) < n:
            self.opps.append(Opp())
        can_raise = "raise" in st["legal_actions"] and st.get("min_raise_to") is not None
        live = [i for i in range(n) if not folded[i] and i != seat]
        # seeded mixed-strategy draw (deterministic per decision point)
        h = (hn * 1000003 + seat * 7919 + len(hist) * 104729 + pot * 31 + c1 * 53 + c2 * 59) & 0xFFFFFFFF
        h ^= h >> 15
        h = (h * 2246822519) & 0xFFFFFFFF
        h ^= h >> 13
        rv = h / 4294967296.0
        if not live:
            return self._legal(("k",), st, to_call, can_raise)
        if not board:
            a = self._preflop(st, seat, c1, c2, pot, to_call, n, live, can_raise, hist, rv)
        else:
            self.rng.seed(h)
            a = self._postflop(st, seat, c1, c2, board, pot, to_call, n, live, can_raise, hist, rv, t0)
        return self._legal(a, st, to_call, can_raise)

    # ------------------------------------------------- bridge: preflop ranges
    def _open_frac(self, o, vpos, size_bb, limpers):
        p = OPENF.get(vpos, 0.15) * (o.pfr_e() / 0.16)
        if o.g > 0:
            p = max(p, o.g * o.pfr_e() * 0.9)     # position-blind raisers
        if limpers:
            p *= 0.85
        typ = o.mean_open() + limpers
        if size_bb > 4.5 and size_bb > 1.6 * typ:  # unusually big raise for this villain: tighter
            p *= max(0.45, 1.6 * typ / size_bb)
        return _clamp(p, 0.015, 1.0)

    def _3b_frac(self, o):
        return _clamp(max(o.tb_e(), 0.5 * o.g * o.pfr_e()), 0.02, 1.0)

    def _4b_frac(self, o):
        return _clamp(max(0.022, 0.45 * o.tb_e(), 0.25 * o.g * o.pfr_e()), 0.015, 1.0)

    def _jam_frac(self, o, level):
        p = o.jam_e()
        if level == 2:
            p = max(p, 0.6 * self._3b_frac(o))
        elif level >= 3:
            p = max(p, 0.6 * self._4b_frac(o))
        if o.jsd_n >= 3:                           # showdown calibration: mean percentile of a top-p range is p/2
            p += o.g * 0.4 * (min(1.0, 2.0 * o.jsd_sum / o.jsd_n) - p)
        return _clamp(p, 0.02, 1.0)

    def _fold_open(self, i, rel):
        o = self.opps[i]
        prior = 0.74 if rel == 1 else 0.60 if rel == 2 else 0.90
        return _clamp(prior + o.g * ((0.72 * 8.0 + o.fr_fold) / (8.0 + o.fr_opp) - 0.72), 0.05, 0.97)

    # ---------------------------------------------------------------- preflop
    def _preflop(self, st, seat, c1, c2, pot, to_call, n, live, can_raise, hist, rv):
        cls = CCLS[CIDX[c1 * 52 + c2]]
        button = st["button"]
        bb = st["big_blind"] or 20
        stacks = st["stacks"]
        bets = st["bets"]
        my_stack = stacks[seat]
        my_bet = bets[seat]
        rel = (seat - button) % n
        pos = _posname(rel, n)
        cur = max(bets)
        nr = 0
        raiser = -1
        limpers = callers = myacts = 0
        lvl = {}
        for e in hist:
            a = e["action"]
            if a == "raise":
                nr += 1
                raiser = e["seat"]
                callers = 0
                lvl[raiser] = nr
            elif a == "call":
                if nr == 0:
                    limpers += 1
                else:
                    callers += 1
            if e["seat"] == seat and a in ("raise", "call", "check"):
                myacts += 1
        hero_ai = (rel - 3) % n
        behind = 0
        for i in live:
            if stacks[i] > 0 and ((myacts == 0 and ((i - button) % n - 3) % n > hero_ai) or bets[i] < cur):
                behind += 1
        total = my_stack + my_bet

        if nr == 0:
            if to_call <= 0:                                   # big blind option
                if can_raise and cls in OPEN["BB"]:
                    return ("r", bb * 3 + bb * limpers)
                return ("k",)
            size = int(bb * (3.0 if pos == "SB" else 2.5)) + bb * limpers
            if cls in OPEN[TIGHTER[pos] if limpers >= 2 else pos]:
                return ("r", size)
            if limpers == 0 and behind <= 3 and can_raise:
                # steal: fixed EV rule, fold probabilities come from the opponent model
                pf = 1.0
                for i in live:
                    if stacks[i] > 0:
                        pf *= self._fold_open(i, (i - button) % n)
                e = eqvs(cls, top_range(0.35))
                ob = size / bb
                evs = pf * 1.5 + (1.0 - pf) * ((0.68 if pos == "SB" else 0.80) * e * (2 * ob + 0.75) - ob) - 0.25
                if evs >= 0.15:
                    return ("r", size)
            if limpers >= 1 and to_call <= bb and cls in LIMP_BEHIND:
                return ("c",)
            if pos == "SB" and limpers >= 1 and to_call <= bb // 2 and POSF[cls] <= 0.60:
                return ("c",)
            return ("f",)

        o = self.opps[raiser]
        vrel = (raiser - button) % n
        vpos = _posname(vrel, n)
        odds = to_call / float(pot + to_call)
        commit = to_call / float(max(total, 1))
        ip = rel == 0 or (rel > vrel and vrel != 0 and rel > 2) or (vrel in (1, 2) and rel > 2) or (vrel == 1 and rel == 2)
        premium = cls in PREMIUM

        if commit >= 0.33 or cur >= 0.4 * self.stack0:
            # facing a shove-sized bet: PF_EQ call range vs each all-in player's measured range
            e = 1.0
            emin = 1.0
            k = 0
            for i in live:
                if bets[i] >= 0.8 * cur:
                    oi = self.opps[i]
                    if i in lvl:
                        p = self._jam_frac(oi, lvl[i])
                    else:
                        p = _clamp(0.05 + oi.g * max(0.0, oi.vpip_e() - 0.45), 0.05, 0.6)
                    x = eqvs(cls, top_range(p))
                    e *= x
                    if x < emin:
                        emin = x
                    k += 1
            if k > 1:
                e = min(emin, e * (1.0 + 0.12 * (k - 1)))
            risk = to_call / float(self.stack0)
            need = odds + ((0.06 - 0.036 * o.g) * risk * risk if risk > 0.10 else 0.0) + 0.012 * behind
            if nr >= 2 and not premium:
                need += 0.04 * (1.0 - o.g)          # multi-raiser all-in guard: non-premium vs unknown ranges
            return ("c",) if e >= need else ("f",)

        multi = callers >= 1
        cheap = to_call <= 0.06 * self.stack0
        r = _play(cls, ip, multi, cheap)
        if rel == 1:
            r *= 0.92
        if nr == 1:
            p = self._open_frac(o, vpos, cur / float(bb), limpers)
            e = eqvs(cls, top_range(p))
            if can_raise and (e >= 0.60 or (cls in V3[pos] and e >= 0.52)):
                amt = int(cur * (3.0 if ip else 4.0)) + cur * callers
                return ("r", 10 ** 7 if amt >= 0.45 * total else amt)
            if can_raise and cls in B3 and callers == 0 and p >= 0.18 and e >= 0.40 and rv < 0.40:
                return ("r", int(cur * (3.0 if ip else 4.0)))
            return ("c",) if e * r >= odds + 0.02 + 0.012 * behind else ("f",)
        if nr == 2:
            p = self._3b_frac(o)
            if lvl.get(raiser) == 2 and vpos in ("CO", "BTN", "SB", "BB"):
                p *= 1.25
            e = eqvs(cls, top_range(p))
            if can_raise and (e >= 0.62 or (cls in V4 and e >= 0.55)):
                amt = int(cur * 2.3)
                return ("r", 10 ** 7 if amt >= 0.40 * total else amt)
            need = odds + (0.03 if ip else 0.05) + (0.04 if my_bet <= bb else 0.0) + 0.012 * behind
            if commit >= 0.40 and not premium:
                need += 0.04 * (1.0 - o.g)
            return ("c",) if e * r >= need else ("f",)
        e = eqvs(cls, top_range(self._4b_frac(o)))
        if can_raise and e >= 0.60:
            return ("r", 10 ** 7)
        need = odds + 0.05 + (0.04 * (1.0 - o.g) if (commit >= 0.40 and not premium) else 0.0)
        return ("c",) if e * r >= need else ("f",)

    # ------------------------------------------------ bridge: postflop ranges
    def _pf_weights(self, v, rl, ca, cl, jm, vrel, n):
        """Preflop class weights of villain v from the action they took (layer 4, step 1)."""
        o = self.opps[v]
        if rl:
            if jm:
                p = self._jam_frac(o, rl)
            elif rl == 1:
                p = self._open_frac(o, _posname(vrel, n), 2.5, 0)
            elif rl == 2:
                p = self._3b_frac(o)
            else:
                p = self._4b_frac(o)
            if ca:
                return band_range(max(0.04, p * 0.7), max(0.01, p * 0.15), 0.5)[0]
            return top_range(p)[0]
        ve = o.vpip_e()
        if cl is None:
            return band_range(1.0, 0.12, 0.4)[0]                # big blind checked its option
        if cl == 0:
            return band_range(_clamp(ve * 1.15, 0.2, 1.0), _clamp(o.pfr_e() * 0.8, 0.03, 0.9), 0.3)[0]
        if cl == 1:
            base = 0.42 if vrel == 2 else 0.20 if vrel == 1 else 0.16
            p = max(base * ve / 0.28, o.g * ve)
            return band_range(_clamp(p, 0.06, 1.0), 0.05, 0.4)[0]
        if cl == 2:
            return band_range(_clamp(0.09 * ve / 0.28, 0.04, 0.7), 0.02, 0.5)[0]
        return top_range(_clamp(0.04 * ve / 0.28, 0.03, 0.5))[0]

    def _order(self, t, board, hm):
        """Live villain combos on street t sorted by current strength (ascending) + board keys."""
        r = self.orders.get(t)
        if r is not None:
            return r
        b = board[:t + 3]
        bk = bs = bmask = 0
        bm = [0, 0, 0, 0]
        sc = [0, 0, 0, 0]
        for c in b:
            bk += RK[c]
            bs += SK[c]
            bmask |= BIT[c]
            bm[c & 3] |= 1 << (c >> 2)
            sc[c & 3] += 1
        dm = bmask | hm
        livec = [i for i in ALLC if not CM[i] & dm]
        if max(sc) >= 3:
            s = []
            ap = s.append
            for i in livec:
                f = FS[bs + CSK[i]]
                ap(NF[bk + CRK[i]] if f < 0 else FL[bm[f] | CSM[f][i]])
        else:
            s = [NF[bk + CRK[i]] for i in livec]
        idx = sorted(range(len(livec)), key=s.__getitem__)
        r = self.orders[t] = ([livec[j] for j in idx], [s[j] for j in idx], bk, bs, bm, dm)
        return r

    def _apply_op(self, ws, v, op, t, prev_agg, wet, allin):
        """Narrow villain v's range by its strongest action on street t (layer 4, step 2 + bridge)."""
        if op is None:
            return ws
        o = self.opps[v]
        code = op[0]
        frac = op[1]
        bl = o.bluff_e()
        if code == 3:                                   # bet: top-f where f = how often this villain bets
            f = o.bet_e(t) + (0.18 if prev_agg else 0.0)
            if frac >= 0.9 and frac > 1.5 * o.mean_bet():
                f *= 0.65                               # big-bet signal
            elif frac <= 0.35:
                f *= 1.12
            if wet:
                f *= 0.9
            if allin and frac > 1.2:
                f *= 0.75
            if op[2] >= 2:
                f *= 0.6
            return _keep_top(ws, _clamp(f, 0.04, 0.98), _clamp(0.10 + 0.6 * (bl - 0.2), 0.03, 0.4))
        if code == 4:                                   # raise: top-f where f = how often they raise
            f = o.raise_e(t)
            fl = _clamp(0.03 + 0.4 * (bl - 0.2), 0.01, 0.2)
            if op[2] >= 2 or allin:
                f *= 0.55
            if wet:
                f *= 0.9
            if o.g >= 0.5 and f < 0.06 and o.fb_opp[t] >= 6:
                f = min(f, 0.04)                        # passive rocket: a passive player's raise is the nuts
                fl = 0.01
            return _keep_top(ws, _clamp(f, 0.025, 0.98), fl)
        if code == 2:                                   # call: drop what this villain folds
            ff = o.fold_e(t) + (0.08 if frac >= 0.9 else -0.10 if frac <= 0.35 else 0.0)
            return _drop_bottom(ws, _clamp(ff, 0.02, 0.85), 0.30 if t < 2 else 0.10, _clamp(o.raise_e(t), 0.02, 0.6), 0.5)
        if code == 1 and prev_agg:                      # aggressor gives up: fewer strong hands
            return _damp_top(ws, _clamp((o.bet_e(t) + 0.18) * 0.5, 0.05, 0.6), 0.5)
        return ws

    # --------------------------------------------------------------- postflop
    def _postflop(self, st, seat, c1, c2, board, pot, to_call, n, live, can_raise, hist, rv, t0):
        si = len(board) - 3
        button = st["button"]
        stacks = st["stacks"]
        bets = st["bets"]
        my_stack = stacks[seat]
        my_bet = bets[seat]
        cur = max(bets)
        hm = BIT[c1] | BIT[c2]
        jam_thr = 0.4 * self.stack0
        # ---- one pass over the hand history
        rl = {}
        ca = {}
        cl = {}
        jm = {}
        ops = ({}, {}, {})
        agg = [-1, -1, -1]
        nrs = [0, 0, 0]
        pfa = -1
        nr = 0
        hp = 0
        b = [0] * n
        curb = 0
        curt = -1
        vraises = {}
        vcr = {}
        for e in hist:
            a = e["action"]
            s = e["seat"]
            if e["street"] == "preflop":
                if a == "raise":
                    amt = e["amount"]
                    nr += 1
                    rl[s] = nr
                    ca[s] = False
                    pfa = s
                    if amt >= jam_thr:
                        jm[s] = True
                    hp += amt - b[s]
                    b[s] = amt
                elif a == "call":
                    if s in rl:
                        ca[s] = True
                    else:
                        cl[s] = nr
                    hp += e["amount"]
                    b[s] += e["amount"]
                elif a == "small_blind" or a == "big_blind":
                    b[s] = e["amount"]
                    hp += e["amount"]
                continue
            t = SIDX[e["street"]]
            if t != curt:
                curt = t
                b = [0] * n
                curb = 0
            if a == "raise":
                amt = e["amount"]
                code = 3 if curb == 0 else 4
                nrs[t] += 1
                d = ops[t].get(s)
                if s != seat:
                    vraises[s] = vraises.get(s, 0) + 1
                    if d is not None and d[0] == 1:
                        vcr[s] = True
                ops[t][s] = (code, (amt - b[s]) / float(max(hp, 1)), nrs[t])
                hp += amt - b[s]
                b[s] = amt
                curb = amt
                agg[t] = s
            elif a == "call":
                amt = e["amount"]
                d = ops[t].get(s)
                if d is None or d[0] < 2:
                    ops[t][s] = (2, amt / float(max(hp - amt, 1)), nrs[t])
                hp += amt
                b[s] += amt
            elif a == "check":
                if s not in ops[t]:
                    ops[t][s] = (1, 0.0, 0)

        # ---- villains to model explicitly (aggressors first), the rest as random hands
        n_opp = len(live)
        a_now = agg[si]
        mod = sorted(live, key=lambda v: (0 if v == a_now else 1, -(vraises.get(v, 0)), 0 if v in rl else 1))
        heavy = self.spent > 3.0
        cap = 2 if heavy else 3
        n_extra = max(0, len(mod) - cap)
        mod = mod[:cap]
        order, sa, bk, bs, bm, dm = self._order(si, board, hm)
        tex = texture(board)
        wet = tex in WET
        vl = []
        pre_ws = None
        for v in mod:
            w = self.w.get(v)
            if w is None:
                cw = self._pf_weights(v, rl.get(v), ca.get(v), cl.get(v), jm.get(v), (v - button) % n, n)
                w = self.w[v] = [cw[c] for c in CCLS]
                self.vdone[v] = 0
            vd = self.vdone[v]
            while vd < si:                               # finalise earlier streets with that street's strengths
                op = ops[vd].get(v)
                if op is not None and op[0] >= 1:
                    od = self._order(vd, board, hm)[0]
                    ws = [w[i] for i in od]
                    ws2 = self._apply_op(ws, v, op, vd, (agg[vd - 1] if vd else pfa) == v,
                                         texture(board[:vd + 3]) in WET, False)
                    if ws2 is not ws:
                        for i, x in zip(od, ws2):
                            w[i] = x
                vd += 1
            self.vdone[v] = si
            op = ops[si].get(v)
            cc = self.wsc.get(v)
            if cc is not None and cc[0] == si and cc[1] == op:
                ws0, ws = cc[2], cc[3]
            else:
                ws0 = [w[i] for i in order]
                ws = self._apply_op(ws0, v, op, si, (agg[si - 1] if si else pfa) == v, wet, stacks[v] == 0)
                self.wsc[v] = (si, op, ws0, ws)
            if v == a_now:
                pre_ws = ws0
            vl.append(ws)

        # ---- layer 4: equity vs the adjusted ranges
        budget = 0.0022 if not heavy else 0.0012
        if self.spent > 6.0:
            budget = 0.0005
        eq, hs = self._equity(si, c1, c2, board, order, sa, bk, bs, bm, dm, vl, n_extra, t0 + budget)
        cls = hs_bucket(c1, c2, board, hs)
        draw = draw_bucket(c1, c2, board)
        sprb = spr_bucket(my_stack, pot)
        ok = [(v - button - 1) % n for v in live]
        me = (seat - button - 1) % n
        pos = 1 if me > max(ok) else 0 if me < min(ok) else 2
        opps = self.opps

        # ---- fold equity inputs from the model (prior by texture/street, moved by measured folds)
        fe_prior = 0.45 + FE_TEX.get(tex, 0.0) - (0.03 if si == 1 else 0.0)
        fes = []
        gmin = 1.0
        for v in live:
            o = opps[v]
            fes.append(_clamp(fe_prior + o.fold_e(si) - FOLDP[si], 0.03, 0.92))
            if o.g < gmin:
                gmin = o.g
        fe_ref = min(fes)
        board_r = [c >> 2 for c in board]
        paired_board = len(set(board_r)) != len(board_r)
        river_pairs = si == 2 and board_r[4] in board_r[:4] and board_r[:4].count(board_r[4]) == 1

        def fe_at(frac):
            """P(all villains fold) to a bet of `frac` pot."""
            bkt = 0 if frac < 0.45 else 1 if frac < 0.9 else 2
            adj = (-0.10, 0.0, 0.08)[bkt] + (0.07 if frac >= 1.4 else 0.0)
            p = 1.0
            for v, f in zip(live, fes):
                p *= _clamp(f + adj + opps[v].szfold_d(bkt), 0.02, 0.95)
            return p

        if to_call <= 0:
            # ================= checked to =================
            shift = _clamp((fe_prior - fe_ref) * 0.5, -0.12, 0.18)   # thin value vs callers, less vs folders
            t = 4 if eq + shift >= 0.76 else 3 if eq + shift >= 0.62 else 2 if eq + shift >= 0.48 else \
                1 if eq + shift >= 0.33 else 0
            d = strat_checked(t, tex, draw, sprb, pos)
            value = t >= 2
            if not value:
                # bluff / semi-bluff rows are scaled by the EV of the bluff under the model's fold equity
                bm_ = BLUFF_MULT[min(n_opp, 5)] if draw < 3 else 1.0
                tot = 0.0
                for k in list(d):
                    if k == "check":
                        continue
                    s = SIZE.get(k, 1.0)
                    pf = fe_at(s)
                    evb = pf + (1.0 - pf) * (0.6 * eq * (1.0 + 2.0 * s) - s) - 0.7 * eq
                    d[k] = d[k] * _clamp(evb * 10.0, 0.0, 2.2) * bm_
                    tot += d[k]
                if tot > 0.97:
                    for k in d:
                        if k != "check":
                            d[k] *= 0.97 / tot
                    tot = 0.97
                d["check"] = 1.0 - tot
                # river nut-flush blocker: bluff a little more
                if si == 2 and t == 0 and fe_ref >= 0.35 and self._blocker(c1, c2, board, cls):
                    mv = 0.12 * d["check"]
                    d["check"] -= mv
                    d["bet_66"] = d.get("bet_66", 0.0) + mv
            act = self._sample(d, rv)
            if act == "check":
                return ("k",)
            if act == "all_in":
                frac = my_stack / float(max(pot, 1))
            else:
                frac = SIZE[act]
            if value and t >= 3:
                # value sizing: largest size whose called-EV gain s*(2eq-1-FE(s)) is clearly better
                best = frac * (2.0 * eq - 1.0 - fe_at(frac))
                smax = my_stack / float(max(pot, 1))
                station = gmin >= 0.5 and fe_ref <= 0.25
                steps = 0
                for s in (0.66, 1.0, 1.5, smax):
                    if s <= frac or s > smax + 1e-9:
                        continue
                    steps += 1
                    if steps > (4 if station else 1):
                        break
                    gsz = s * (2.0 * eq - 1.0 - fe_at(s))
                    if gsz > best * 1.15 and gsz > 0:
                        best = gsz
                        frac = s
            # ---- governors on bets
            if si == 2 and paired_board and n_opp >= 2 and cls < TRIPS and eq < 0.80:
                return ("k",)                               # multiway paired-river super-cap
            if river_pairs and cls < FULL and eq < 0.88:
                frac = min(frac, 0.66)                      # river card paired the board: cap aggression
            amt = cur + int(frac * pot)
            add = amt - my_bet
            if add >= 0.40 * (my_stack + my_bet) and value:
                danger = self._danger(board, board_r, tex, cls, c1, c2, a_now, vraises, vcr)
                need = 0.70 + 0.03 * danger + 0.06 * _sig((my_stack / float(max(pot, 1)) - 3.0) / 1.2)
                if eq < need:
                    amt = cur + int(min(frac, 0.66) * pot)  # stack-off check failed: keep the pot smaller
                    if amt - my_bet >= 0.40 * (my_stack + my_bet):
                        return ("k",) if eq < need - 0.08 else ("r", amt)
            return ("r", amt)

        # ================= facing a bet / raise =================
        odds = to_call / float(pot + to_call)
        betfrac = to_call / float(max(pot - to_call, 1))
        total = my_stack + my_bet
        commit = to_call / float(max(total, 1))
        risk = to_call / float(self.stack0)
        oa = opps[a_now] if a_now >= 0 else None
        ga = oa.g if oa is not None else 0.0
        kind = oa.kind() if oa is not None else "unknown"
        req = odds
        if risk > 0.10:
            req += (0.06 - 0.03 * ga) * risk * risk          # variance penalty (model-error insurance)
        danger = 0
        if commit >= 0.40:
            danger = self._danger(board, board_r, tex, cls, c1, c2, a_now, vraises, vcr)
            if kind in ("maniac", "shover"):
                danger = max(0, danger - 1)
            req += 0.05 * _sig((my_stack / float(max(pot, 1)) - 3.0) / 1.2) + 0.015 * danger
        behind = 0
        for v in live:
            if bets[v] < cur and stacks[v] > 0:
                behind += 1
        req += 0.02 * behind
        if si < 2 and draw >= 3 and my_stack > to_call:
            req -= 0.04                                      # implied odds for strong draws
        if si == 2 and cls < TWOP and kind not in ("maniac", "shover"):
            req += 0.03 * min(1.0, betfrac)                  # river value respect (bluff-catchers over-pay)
        t = 4 if eq >= 0.76 else 3 if eq >= 0.62 else 2 if eq >= 0.48 else 1 if eq >= 0.33 else 0
        pressure = 3 if (my_bet > 0 or betfrac >= 1.2) else 2 if betfrac >= 0.8 else 1 if betfrac >= 0.45 else 0
        if eq < req:
            # river MDF defence: call the top of our bluff-catchers when only just short
            if (si == 2 and pre_ws is not None and eq >= req - 0.07 and n_opp == 1
                    and kind in ("unknown", "balanced", "maniac", "tag")):
                mdf = 1.0 - betfrac / (1.0 + betfrac)
                cum = list(accumulate(pre_ws))
                if cum and cum[-1] > 0:
                    lo = bisect_left(sa, hs)
                    wide = (cum[lo - 1] if lo else 0.0) / cum[-1]
                    if wide >= 1.0 - mdf + 0.10:
                        return ("c",)
            return ("f",)
        d = strat_facing(t, draw, sprb, pos, pressure)
        # equity rule: with the price met we never fold; raises need a value tier or a strong draw
        x = d.pop("fold", 0.0)
        d["call"] = d.get("call", 0.0) + x
        if t < 3:
            keep = draw >= 3 and si < 2 and n_opp == 1 and fe_ref >= fe_prior - 0.05
            for k in ("raise_pot", "raise_value", "all_in"):
                if k in d and not (keep and k == "raise_pot"):
                    d["call"] += d.pop(k)
        act = self._sample(d, rv)
        if act == "call" or not can_raise:
            return ("c",)
        if act == "all_in":
            amt = total
        elif act == "raise_pot":
            amt = cur + pot + to_call
        else:
            amt = max(int(cur * 2.5), cur + int(0.6 * (pot + to_call)))
        # ---- governors on raises
        if si == 2 and paired_board and n_opp >= 2 and cls < TRIPS and eq < 0.85:
            return ("c",)
        if river_pairs and cls < FULL and eq < 0.88:
            return ("c",)
        if amt - my_bet >= 0.40 * total:
            if not danger:
                danger = self._danger(board, board_r, tex, cls, c1, c2, a_now, vraises, vcr)
            need = 0.70 + 0.03 * danger + 0.06 * _sig((my_stack / float(max(pot, 1)) - 3.0) / 1.2)
            if eq < need or (danger >= 2 and WTP <= cls <= TRIPS and kind not in ("maniac", "shover") and eq < 0.90):
                return ("c",)
        return ("r", amt)

    def _sample(self, d, rv):
        tot = 0.0
        for v in d.values():
            if v > 0:
                tot += v
        if tot <= 0:
            return "check" if "check" in d else "call"
        c = 0.0
        last = None
        for k in sorted(d):
            v = d[k]
            if v <= 0:
                continue
            c += v / tot
            last = k
            if rv < c:
                return k
        return last

    def _blocker(self, c1, c2, board, cls):
        """River: we hold the nut-flush blocker on a three-flush board (and no flush ourselves)."""
        if cls >= FLSH:
            return False
        sc = [0, 0, 0, 0]
        for c in board:
            sc[c & 3] += 1
        for s in range(4):
            if sc[s] == 3:
                top = 48 + s
                if top in board:
                    top = 44 + s
                    if top in board:
                        continue
                if (c1 == top) != (c2 == top) and not ((c1 & 3) == s and (c2 & 3) == s):
                    return True
        return False

    def _danger(self, board, br, tex, cls, c1, c2, vill, vraises, vcr):
        """GrandSlam nut-danger score: how likely the board/line holds a hand that crushes ours."""
        s = 0
        cnt = {}
        for r in br:
            cnt[r] = cnt.get(r, 0) + 1
        npair = sum(1 for v in cnt.values() if v >= 2)
        trips_b = any(v >= 3 for v in cnt.values())
        if npair:
            s += 1
        if npair >= 2:
            s += 2
        if trips_b:
            s += 2
        sc = [0, 0, 0, 0]
        for c in board:
            sc[c & 3] += 1
        ms = max(sc)
        if ms >= 5:
            s += 1
        if ms >= 4:
            s += 2
        vs = sorted(cnt)
        if len(vs) >= 4:
            for i in range(len(vs) - 3):
                if vs[i + 3] - vs[i] <= 4:
                    s += 1
                    break
        if tex in ("monotone", "broadway_connected", "low_connected", "connected"):
            s += 1
        if vill >= 0:
            if vcr.get(vill):
                s += 2
            if vraises.get(vill, 0) >= 2:
                s += 2
        if ms >= 3:
            fs = sc.index(ms)
            if c1 == 48 + fs or c2 == 48 + fs:
                s -= 1
        if cls == FULL and npair:
            s -= 3
        if cls >= STRT:
            s -= 1
        if cls == TRIPS and not trips_b and npair < 2:
            s -= 1
        return s if s > 0 else 0

    # ------------------------------------------------------------ equity core
    def _equity(self, si, c1, c2, board, order, sa, bk, bs, bm, dm, vl, n_extra, dl):
        """Hero equity vs the weighted villain ranges. Exact on the river, sampled before."""
        hk = RK[c1] + RK[c2]
        hsk = SK[c1] + SK[c2]
        hsm = (SBIT[0][c1] | SBIT[0][c2], SBIT[1][c1] | SBIT[1][c2],
               SBIT[2][c1] | SBIT[2][c2], SBIT[3][c1] | SBIT[3][c2])
        f = FS[bs + hsk]
        hs = NF[bk + hk] if f < 0 else FL[bm[f] | hsm[f]]
        cums = []
        for ws in vl:
            cum = list(accumulate(ws))
            if cum and cum[-1] > 1e-12:
                cums.append(cum)
            else:
                n_extra += 1                         # degenerate range: treat as a random hand
        nl = len(sa)
        if si == 2:
            lo = bisect_left(sa, hs)
            hi = bisect_right(sa, hs)
            eq = 1.0
            for cum in cums:
                win = cum[lo - 1] if lo else 0.0
                tie = (cum[hi - 1] if hi else 0.0) - win
                eq *= (win + 0.5 * tie) / cum[-1]
            if n_extra:
                eq *= ((lo + 0.5 * (hi - lo)) / float(nl)) ** n_extra
            return eq, hs
        ch = self.rng.choices
        deck = [c for c in range(52) if not BIT[c] & dm]
        nv = len(cums) + n_extra
        win = tie = cnt = 0
        chunk = 96
        target = 480 if nv == 1 else 336 if nv == 2 else 256
        if si == 1:
            riv = [None] * 52
            for r in deck:
                k = bk + RK[r]
                s = bs + SK[r]
                m = (bm[0] | SBIT[0][r], bm[1] | SBIT[1][r], bm[2] | SBIT[2][r], bm[3] | SBIT[3][r])
                f = FS[s + hsk]
                riv[r] = (k, s, m, NF[k + hk] if f < 0 else FL[m[f] | hsm[f]])
            while cnt < target:
                rs = ch(deck, k=chunk)
                if nv == 1:
                    vi = ch(order, cum_weights=cums[0], k=chunk) if cums else ch(order, k=chunk)
                    for i, r in zip(vi, rs):
                        if CM[i] & BIT[r]:
                            continue
                        k, s, m, h = riv[r]
                        f = FS[s + CSK[i]]
                        v = NF[k + CRK[i]] if f < 0 else FL[m[f] | CSM[f][i]]
                        if h > v:
                            win += 1
                        elif h == v:
                            tie += 1
                        cnt += 1
                else:
                    smp = [ch(order, cum_weights=cum, k=chunk) for cum in cums]
                    for _ in range(n_extra):
                        smp.append(ch(order, k=chunk))
                    for j in range(chunk):
                        r = rs[j]
                        used = BIT[r]
                        k, s, m, h = riv[r]
                        res = 2
                        for sm in smp:
                            i = sm[j]
                            if CM[i] & used:
                                res = -1
                                break
                            used |= CM[i]
                            f = FS[s + CSK[i]]
                            v = NF[k + CRK[i]] if f < 0 else FL[m[f] | CSM[f][i]]
                            if v > h:
                                res = 0
                            elif v == h and res == 2:
                                res = 1
                        if res < 0:
                            continue
                        if res == 2:
                            win += 1
                        elif res == 1:
                            tie += 1
                        cnt += 1
                if _pc() > dl:
                    break
        else:
            sb0, sb1, sb2, sb3 = SBIT
            sbl = SBIT
            while cnt < target:
                ts = ch(deck, k=chunk)
                rs = ch(deck, k=chunk)
                smp = [ch(order, cum_weights=cum, k=chunk) for cum in cums]
                for _ in range(n_extra):
                    smp.append(ch(order, k=chunk))
                for j in range(chunk):
                    tc = ts[j]
                    r = rs[j]
                    if tc == r:
                        continue
                    used = BIT[tc] | BIT[r]
                    k = bk + RK[tc] + RK[r]
                    s = bs + SK[tc] + SK[r]
                    f = FS[s + hsk]
                    if f < 0:
                        h = NF[k + hk]
                    else:
                        fb = sbl[f]
                        h = FL[bm[f] | fb[tc] | fb[r] | hsm[f]]
                    res = 2
                    for sm in smp:
                        i = sm[j]
                        if CM[i] & used:
                            res = -1
                            break
                        used |= CM[i]
                        f = FS[s + CSK[i]]
                        if f < 0:
                            v = NF[k + CRK[i]]
                        else:
                            fb = sbl[f]
                            v = FL[bm[f] | fb[tc] | fb[r] | CSM[f][i]]
                        if v > h:
                            res = 0
                        elif v == h and res == 2:
                            res = 1
                    if res < 0:
                        continue
                    if res == 2:
                        win += 1
                    elif res == 1:
                        tie += 1
                    cnt += 1
                if _pc() > dl:
                    break
        if cnt == 0:
            return 0.5, hs
        return (win + 0.5 * tie) / cnt, hs

    # ------------------------------------------------- layer 2: learn villains
    def on_hand_end(self, summary):
        try:
            self._learn(summary)
        except Exception:
            self.errs += 1

    def _learn(self, sm):
        hist = sm.get("history") or []
        opps = self.opps
        n = self.n
        bb = float(self.bb)
        jam_thr = 0.4 * self.stack0
        b = [0] * n
        cur = 0
        pot = 0
        street = "preflop"
        t = -1
        nr = 0
        vp = [0] * n
        pr = [0] * n
        jm = [0] * n
        faced = [0] * n
        rpf = [0] * n
        late = [0] * n
        for e in hist:
            a = e["action"]
            s = e["seat"]
            amt = e.get("amount") or 0
            if s >= n:
                continue
            if e["street"] != street:
                street = e["street"]
                b = [0] * n
                cur = 0
                t = SIDX.get(street, 2)
            if a == "small_blind" or a == "big_blind":
                b[s] = amt
                pot += amt
                if amt > cur:
                    cur = amt
                continue
            o = opps[s]
            o.n += 1
            if t < 0:
                if cur >= 12 * bb and cur > b[s]:
                    o.pc_opp += 1
                    if a != "fold":
                        o.pc_n += 1
                if nr == 1 and not faced[s] and not rpf[s]:
                    faced[s] = 1
                    o.fr_opp += 1
                    if a == "fold":
                        o.fr_fold += 1
                    elif a == "raise":
                        o.fr_3b += 1
                elif nr >= 2 and rpf[s]:
                    o.f3_opp += 1
                    if a == "fold":
                        o.f3_fold += 1
                if a == "raise":
                    if nr == 0:
                        o.rs_sum += amt / bb
                        o.rs_n += 1
                    nr += 1
                    rpf[s] = 1
                    vp[s] = pr[s] = 1
                    if amt >= jam_thr:
                        jm[s] = 1
                elif a == "call":
                    vp[s] = 1
            else:
                tc = cur - b[s]
                if tc <= 0:
                    o.b_opp[t] += 1
                    if a == "raise":
                        o.b_n[t] += 1
                        o.bs_sum += min(3.0, (amt - b[s]) / float(max(pot, 1)))
                        o.bs_n += 1
                else:
                    fr = tc / float(max(pot - tc, 1))
                    k = 0 if fr < 0.45 else 1 if fr < 0.9 else 2
                    o.fb_opp[t] += 1
                    o.sz_opp[k] += 1
                    if a == "fold":
                        o.fb_fold[t] += 1
                        o.sz_fold[k] += 1
                    elif a == "raise":
                        o.fb_raise[t] += 1
                if a == "raise" and t >= 1:
                    late[s] = 1
            if a == "raise":
                pot += amt - b[s]
                b[s] = amt
                cur = amt
            elif a == "call":
                pot += amt
                b[s] += amt
        shown = sm.get("shown") or {}
        board = sm.get("board") or []
        bc = [CARD[x] for x in board] if len(board) == 5 else None
        for i in range(n):
            o = opps[i]
            o.hands += 1
            o.vpip += vp[i]
            o.pfr += pr[i]
            o.jam += jm[i]
            g = (o.n - 20) / 40.0
            o.g = 0.0 if g < 0 else 1.0 if g > 1 else g
        for ks, cards in shown.items():
            s = int(ks)
            if s == self.seat or s >= n or len(cards) != 2:
                continue
            x, y = CARD[cards[0]], CARD[cards[1]]
            o = opps[s]
            if jm[s]:
                o.jsd_n += 1
                o.jsd_sum += POSF[CCLS[CIDX[x * 52 + y]]]
            if late[s] and bc is not None:
                o.sd_agg += 1
                if ev(bc + [x, y]) >> 20 == 0:
                    o.sd_weak += 1


gc.collect()
gc.freeze()
gc.disable()
