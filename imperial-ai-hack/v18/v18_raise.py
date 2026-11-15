"""Pokerbot v18 (= v14 + V18_* randomised out-of-plan aggression; v14 = = v13.1 + v12 aggression switches B1/B2/B3/B5; v13.1 = v11.1 + data-checked exploits, review fixes applied, see V13_*; v11.1 = v10 + Sunday fixes from the 36-round diagnosis; see V11_* switches): EV maximiser with frequency-derived ranges (Hyperion-style four layers).

Layer 1  decision engine  : explicit chip EV per candidate action (fold/check/call, bets at
                            1/3, 2/3, pot, overbet, all-in), fixed opponent-independent formulas.
Layer 2  opponent model   : per-seat action frequencies with Beta priors (class Opp).
Layer 3  exploit bridge   : turns frequencies into ranges ("top p of hands for that action"),
                            gated by g = clamp((n - 20) / 40, 0, 1). It only changes ranges.
Layer 4  equity engine    : per-combo weights for every live villain, updated by the likelihood
                            of each action; exact river enumeration, Monte Carlo before it.
Standard library only, no I/O, never raises out of act().
"""
import base64
import gc
import random
import time
import zlib
from bisect import bisect_left
from itertools import accumulate
from math import exp, log
from operator import mul

_pc = time.perf_counter
_rng = random.Random()
_choices = _rng.choices

# --------------------------------------------------------------------------- preflop data
_R = "AKQJT98765432"
PF_COMBOS = []
for _i in range(13):
    for _j in range(13):
        PF_COMBOS.append(6 if _i == _j else (4 if _i < _j else 12))

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


def _rank_classes():
    """Playability-adjusted strength score per class (used for 'top p' ranges)."""
    s1 = PF_VS_RANDOM
    idx = sorted(range(169), key=lambda c: -s1[c])
    tot = 0
    top = []
    for c in idx:
        if tot > 0.3 * 1326:
            break
        top.append(c)
        tot += PF_COMBOS[c]
    wsum = float(sum(PF_COMBOS[c] for c in top))
    s2 = [sum(PF_EQ[a][b] * PF_COMBOS[b] for b in top) / wsum for a in range(169)]
    out = []
    for c in range(169):
        i, j = divmod(c, 13)
        adj = 0.0
        if i < j:
            adj = 0.022 + (0.012 if j - i <= 2 else 0.0)
        elif i > j and i - j >= 5:
            adj = -0.01
        out.append(0.5 * s1[c] + 0.5 * s2[c] + adj)
    return out


_SCORE = _rank_classes()
ORDER_ASC = sorted(range(169), key=lambda c: _SCORE[c])      # weakest class first
POS_OF = [0] * 169
for _p, _c in enumerate(ORDER_ASC):
    POS_OF[_c] = _p
MASS0 = [float(PF_COMBOS[c]) for c in ORDER_ASC]             # uniform range, mass per class
INVC = [1.0 / PF_COMBOS[c] for c in range(169)]
PCT = [0.0] * 169                                            # 0 = best hand, 1 = worst
_acc = 0.0
for _c in reversed(ORDER_ASC):
    PCT[_c] = (_acc + 0.5 * PF_COMBOS[_c]) / 1326.0
    _acc += PF_COMBOS[_c]
EQROW = [[PF_EQ[h][c] for c in ORDER_ASC] for h in range(169)]

# --------------------------------------------------------------------------- evaluator
RANKS = "23456789TJQKA"
SUITS = "cdhs"
CARD = {r + s: RANKS.index(r) * 4 + SUITS.index(s) for r in RANKS for s in SUITS}
RK = [5 ** (c >> 2) for c in range(52)]
SK = [8 ** (c & 3) for c in range(52)]
BIT = [1 << c for c in range(52)]
CARD_SM = [tuple((1 << (c >> 2)) if (c & 3) == s else 0 for s in range(4)) for c in range(52)]


def _straights():
    t = [-1] * 8192
    for m in range(8192):
        mm = (m << 1) | (1 if m & 4096 else 0)
        for top in range(13, 3, -1):
            if (mm >> (top - 4)) & 31 == 31:
                t[m] = top - 1
                break
    return t


STR = _straights()


def _build_nf():
    """Strength of every 5/6/7-card rank multiset ignoring flushes; key = sum of 5**rank."""
    nf = {}
    cnt = [0] * 13
    p5 = [5 ** r for r in range(13)]
    strt = STR

    def val():
        q = t1 = t2 = -1
        prs = []
        sg = []
        m = 0
        for r in range(12, -1, -1):
            n = cnt[r]
            if n:
                m |= 1 << r
                if n == 1:
                    sg.append(r)
                elif n == 2:
                    prs.append(r)
                elif n == 3:
                    if t1 < 0:
                        t1 = r
                    elif t2 < 0:
                        t2 = r
                else:
                    q = r
        if q >= 0:
            k = -1
            for r in range(12, -1, -1):
                if cnt[r] and r != q:
                    k = r
                    break
            return (7 << 20) | (q << 16) | (k << 12)
        if t1 >= 0 and (t2 >= 0 or prs):
            return (6 << 20) | (t1 << 16) | ((t2 if t2 >= 0 else prs[0]) << 12)
        sh = strt[m]
        if sh >= 0:
            return (4 << 20) | (sh << 16)
        if t1 >= 0:
            return (3 << 20) | (t1 << 16) | (sg[0] << 12) | (sg[1] << 8)
        if len(prs) >= 2:
            k = -1
            for r in range(12, -1, -1):
                if cnt[r] and r != prs[0] and r != prs[1]:
                    k = r
                    break
            return (2 << 20) | (prs[0] << 16) | (prs[1] << 12) | (k << 8)
        if prs:
            return (1 << 20) | (prs[0] << 16) | (sg[0] << 12) | (sg[1] << 8) | (sg[2] << 4)
        return (sg[0] << 16) | (sg[1] << 12) | (sg[2] << 8) | (sg[3] << 4) | sg[4]

    def rec(r, used, key):
        if r == 13:
            if used >= 5:
                nf[key] = val()
            return
        p = p5[r]
        top = 7 - used
        if top > 4:
            top = 4
        for n in range(top + 1):
            cnt[r] = n
            rec(r + 1, used + n, key + n * p)
        cnt[r] = 0

    rec(0, 0, 0)
    return nf


NF = _build_nf()


def _build_fl():
    fl = [0] * 8192
    for m in range(8192):
        if bin(m).count("1") >= 5:
            sh = STR[m]
            if sh >= 0:
                fl[m] = (8 << 20) | (sh << 16)
            else:
                rs = [r for r in range(12, -1, -1) if (m >> r) & 1][:5]
                fl[m] = (5 << 20) | (rs[0] << 16) | (rs[1] << 12) | (rs[2] << 8) | (rs[3] << 4) | rs[4]
    return fl


FL = _build_fl()
FS = [-1] * 4096
for _k in range(4096):
    for _s in range(4):
        if (_k >> (3 * _s)) & 7 >= 5:
            FS[_k] = _s
SD = [0] * 8192                       # number of ranks completing a straight (0, 1, 2)
for _m in range(8192):
    if STR[_m] < 0:
        _n = 0
        for _r in range(13):
            if not (_m >> _r) & 1 and STR[_m | (1 << _r)] >= 0:
                _n += 1
        SD[_m] = _n


def ev7(cards):
    """Strength int of the best 5-card hand from 5..7 card ints (same ordering as the engine)."""
    rk = sk = 0
    for c in cards:
        rk += RK[c]
        sk += SK[c]
    fs = FS[sk]
    if fs >= 0:
        m = 0
        for c in cards:
            if c & 3 == fs:
                m |= 1 << (c >> 2)
        return FL[m]
    return NF[rk]


# --------------------------------------------------------------------------- combo tables
CM = []
RKS = []
SKS = []
CSM = []
CLS = []
KID = [0] * 2704
CARD_COMBOS = [[] for _ in range(52)]
SUITED = [[] for _ in range(4)]
_rp = {}
for _a in range(52):
    for _b in range(_a + 1, 52):
        _k = len(CM)
        KID[_a * 52 + _b] = _k
        KID[_b * 52 + _a] = _k
        CM.append((1 << _a) | (1 << _b))
        RKS.append(RK[_a] + RK[_b])
        SKS.append(SK[_a] + SK[_b])
        CSM.append(tuple(x | y for x, y in zip(CARD_SM[_a], CARD_SM[_b])))
        _i, _j = 12 - (_a >> 2), 12 - (_b >> 2)
        if _i == _j:
            CLS.append(_i * 13 + _j)
        else:
            _hi, _lo = (_i, _j) if _i < _j else (_j, _i)
            CLS.append(_hi * 13 + _lo if (_a & 3) == (_b & 3) else _lo * 13 + _hi)
        CARD_COMBOS[_a].append(_k)
        CARD_COMBOS[_b].append(_k)
        if (_a & 3) == (_b & 3):
            SUITED[_a & 3].append(_k)
        _rp.setdefault((1 << (_a >> 2)) | (1 << (_b >> 2)), []).append(_k)
RPAIRS = list(_rp.items())
ALLK = list(range(1326))

# --------------------------------------------------------------------------- constants
NB = 48                 # likelihood look-up resolution (percentile grid)
_INB = 1.0 / NB
NBK = 12                # equity buckets over the villain's range percentile
_INBK = 1.0 / NBK
UNI = [_INBK] * NBK
VPEN = 0.09             # variance penalty coefficient (insurance against range-model error)
# ---- v12 switches (each can be turned off for A/B tests)
V12_FOLD_BLEND = 0.5    # share of a villain's calls modelled as independent of his hand (fold model was overconfident)
V12_HU_BLUFF = True     # heads-up bluff sizes up to 1.05 pot when checked to (turn/river caps: V13 line-aware caps)
V12_VALUE = True        # overbets from uh 0.80 (was 0.90); big HU bets vs measured sticky callers from uh 0.76
V12_LIGHT3 = True       # light 3-bets vs openers measured folding >= 55% to 3-bets (ace / pair / suited connector)
FOLD_P = (0.28, 0.50, 0.60, 0.72) if V12_FOLD_BLEND > 0 else (0.25, 0.47, 0.52, 0.67)   # v12: measured R19-R54
RAISE_P = (0.12, 0.13, 0.08, 0.06)    # real-field raise-vs-bet by price bucket
BET_P = (0.0, 0.60, 0.56, 0.47)       # v11: measured R19-R54 bet-when-checked-to by street (v10 .55/.48/.39)
BLUFF_SH = (0.0, 0.30, 0.25, 0.20)    # share of a betting range that is air, by street
UB = (0.50, 0.60, 0.69, 0.79)         # share of all hands too weak to continue, by bucket
OPEN_P = (0.20, 0.55, 0.60, 0.42, 0.32, 0.26, 0.21, 0.18)    # open % by players behind
POSF = (0.6, 1.6, 1.8, 1.25, 1.0, 0.85, 0.72, 0.62)          # villain open-freq position factor
# ---- v11 switches (each can be turned off for A/B tests)
V11_TFL = 0.0           # OFF (tested: global tempering made us call too much in the duel bench; river fixes below kept)
V11_MDF_ALWAYS = True   # river minimum-defence floor for every opponent who is not a measured honest bettor
V11_PRICE_GUARD = 0.25  # stack-off / one-pair guards only fire when the price tc / (pot + tc) is at least this
V11_JAM_FIX = True      # re-jams over a raise use the context re-raise rate (floor 25%), not the open-shove rate
V11_PF_VPEN = 0.04      # variance penalty when calling a preflop shove (v10 used VPEN = 0.09)
V11_MC_DL = 0.0035      # Monte Carlo deadline per decision (v10 2.1 ms; real limit 25 ms incl. transport)
V11_UPD_DL = 0.0025     # postflop range-update cut-off (v10 1.3 ms)
V11_OVERHEAD = 0.0010   # transport/serialisation time per decision counted against the 10 s bank
V11_MC_SKIP = 0.0055    # skip the Monte Carlo when a decision is already this far in (slow server)
V11_HARD_DL = 0.0080    # hard cap: past this, return the passive choice without evaluating bets/raises
V11_FLOP_RZ = 0.85      # flop call realisation multiplier for weak pairs / air without a strong draw
V11_RIVER_CATCH = True  # call heads-up river bets <= 0.6 pot with top pair+ unless the bettor is measured honest
V11_HONESTY = False     # OFF (tested: the air-only gate blocked profitable top-pair bluff-catches)
V11_3BET_DEF = True     # continue vs 3-bets by how often THAT villain 3-bets our opens; 4-bet-bluff measured folders
# ---- v13 switches (data-checked exploits; each can be turned off for A/B tests)
V13_WEAKPAIR = True     # heads-up river bets <= 0.55 pot: call with a pair that uses a hole card (field: 35% air)
V13_RIVER_BLSH = False  # OFF after review (no evidence at Table C): river first-bet air share in the range model by size: .34 / .26 / .20 (measured 35/27/11%)
V13_4BET_WIDE = True    # wider 4-bet bluffs vs measured 4-bet folders who 3-bet our opens often (FisherMen: 83%)
V13_LINE_BLUFF = True   # heads-up turn/river bluff caps by betting line (capped ranges fold 66-80%, OOP barrels 32-38%)
V18_AIR_P = 0.0        # v18: share of hands where a cap-blocked air bluff (model EV above checking) is allowed anyway
V18_THIN_P = 0.0       # v18: share of near-indifferent checked-to spots where we bet instead of checking
V18_TOL = 0.04          # v18: ... near-indifferent = best bet EV within this share of the pot below checking
V18_RAISE_P = 0.35      # v18: share of heads-up flop/turn small leads (<= 0.4 pot) we may bluff-raise (real logs: 61-77% fold)
V18_PF_P = 0.0         # v18: share of single-open spots where a light 3-bet is allowed vs openers not measured to defend
V13_IP_RAISE = False    # OFF after review (gate never fires vs Table C): raise a measured raise-folder's led flop/turn bet in position (FisherMen folds 94% / 86%)
STREET_IDX = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
FOLD = {"action": "fold"}
CHECK = {"action": "check"}
CALL = {"action": "call"}


def _top(q, tau, floor=0.0):
    """Likelihood table for 'top q of the current range' with a soft edge of width tau."""
    lo = 1.0 - q
    inv = 1.0 / tau
    return [min(1.0, max(floor, ((i + 0.5) * _INB - lo) * inv + 0.5)) for i in range(NB)]


def _apply(ws, t):
    """Multiply range weights (sorted weakest -> strongest) by a percentile likelihood table."""
    acc = list(accumulate(ws))
    tot = acc[-1]
    if tot <= 1e-12:
        return ws
    sc = NB / tot * 0.999999
    return [w * t[int(a * sc)] for w, a in zip(ws, acc)]


def _bucket(tc, pot_incl):
    """Price bucket of a call of tc into a pot that already includes the bet."""
    rho = tc / pot_incl if pot_incl > 0 else 1.0
    return 0 if rho < 0.30 else (1 if rho < 0.45 else (2 if rho < 0.58 else 3))


def _uninf(n, ssum, q):
    """Showdown calibration: how uninformative are this villain's raises (0 = top-q, 1 = random)."""
    if n < 2:
        return 0.0
    u = (ssum / n - 0.5 * q) / max(0.05, 0.5 - 0.5 * q)
    return min(1.0, max(0.0, u)) * n / (n + 3.0)


# --------------------------------------------------------------------------- layer 2: opponent model
class Opp:
    __slots__ = ("n", "g", "uo_n", "uo_r", "uo_l", "fr_n", "fr_c", "fr_r", "f3_n", "f3_c", "f3_r",
                 "fs_n", "fs_c", "fd_n", "fd_sh", "cb_n", "cb_b", "fb_n", "fb_f", "fb_r",
                 "bs_n", "bs_sum", "sd_r_n", "sd_r_sum", "sd_s_n", "sd_s_sum",
                 "d3_n", "d3_c", "d3_r", "d4_n", "d4_c", "d4_r", "ds_n", "ds_c", "br_n", "br_f",
                 "ra_n", "ra_air", "tu_n", "tu_r")

    def __init__(self):
        self.n = 0              # observed voluntary actions
        self.g = 0.0            # gating weight
        self.uo_n = self.uo_r = self.uo_l = 0       # unopened pot: chances / raises / limps
        self.fr_n = self.fr_c = self.fr_r = 0       # facing one raise: chances / calls / 3-bets
        self.f3_n = self.f3_c = self.f3_r = 0       # facing 3-bet+: chances / calls / re-raises
        self.fs_n = self.fs_c = 0                   # facing a shove cold: chances / calls
        self.d3_n = self.d3_c = self.d3_r = 0       # as the raiser, facing a 3-bet: chances / calls / re-raises
        self.d4_n = self.d4_c = self.d4_r = 0       # as a re-raiser, facing a 4-bet+
        self.ds_n = self.ds_c = 0                   # facing a shove after having raised: chances / calls
        self.br_n = self.br_f = 0                   # postflop, bet and got raised: chances / folds
        self.fd_n = self.fd_sh = 0                  # hands seen / hands with a preflop shove
        self.cb_n = [0, 0, 0, 0]                    # postflop, checked to: chances by street
        self.cb_b = [0, 0, 0, 0]                    # ... bets
        self.fb_n = [0, 0, 0, 0]                    # facing a bet, by price bucket: chances
        self.fb_f = [0, 0, 0, 0]                    # ... folds
        self.fb_r = [0, 0, 0, 0]                    # ... raises
        self.bs_n = 0
        self.bs_sum = 0.0                           # bet sizes as pot fractions
        self.sd_r_n = 0
        self.sd_r_sum = 0.0                         # showdown percentiles after a preflop raise
        self.sd_s_n = 0
        self.sd_s_sum = 0.0                         # ... after a preflop shove
        self.ra_n = 0                               # v11: his first river bets seen at showdown
        self.ra_air = 0                             # ... of which air (high card / board-only pair)
        self.tu_n = 0                               # v11: times he faced OUR open (first raise preflop)
        self.tu_r = 0                               # ... and 3-bet it

    def f(self, k, n, prior, kk):
        """Beta-posterior frequency, shrunk to the population prior by the gate."""
        return prior + self.g * ((k + prior * kk) / (n + kk) - prior)

    def foldp(self, b):
        fn = self.fb_n
        ff = self.fb_f
        tn = fn[0] + fn[1] + fn[2] + fn[3]
        base = FOLD_P[b]
        if tn:
            ex = (fn[0] * FOLD_P[0] + fn[1] * FOLD_P[1] + fn[2] * FOLD_P[2] + fn[3] * FOLD_P[3]) / tn
            ob = (ff[0] + ff[1] + ff[2] + ff[3]) / tn
            base = min(0.97, max(0.01, base + (ob - ex) * tn / (tn + 8.0)))
        post = (ff[b] + base * 5.0) / (fn[b] + 5.0)
        return FOLD_P[b] + self.g * (post - FOLD_P[b])

    def raisep(self, b):
        fn = self.fb_n
        fr = self.fb_r
        tn = fn[0] + fn[1] + fn[2] + fn[3]
        base = RAISE_P[b]
        if tn:
            ob = (fr[0] + fr[1] + fr[2] + fr[3] + 0.08 * 6.0) / (tn + 6.0)
            base = min(0.9, max(0.005, base * ob / 0.08))
        post = (fr[b] + base * 5.0) / (fn[b] + 5.0)
        return RAISE_P[b] + self.g * (post - RAISE_P[b])

    def callraised(self, frac):
        """P(calls a shove) for a villain who has already raised; frac = his range as a share of all hands."""
        pr = min(0.92, max(0.25, 0.085 / max(frac, 0.02)))
        return pr + self.g * ((self.ds_c + pr * 4.0) / (self.ds_n + 4.0) - pr)

    def foldraise(self):
        """P(folds) after betting and getting raised."""
        return self.f(self.br_f, self.br_n, 0.38, 6.0)

    def callshove(self):
        c = self.f(self.fr_c + self.fr_r, self.fr_n, 0.20, 10.0)
        pr = min(0.9, max(0.04, c ** 4))
        return 0.06 + self.g * ((self.fs_c + pr * 5.0) / (self.fs_n + 5.0) - 0.06)

    def air(self):
        """v11: share of his first river bets that were air, Beta-shrunk to the field's 0.21 (k = 4)."""
        return (self.ra_air + 0.21 * 4.0) / (self.ra_n + 4.0)

    def air2(self):
        """v13: share of his first river bets that were air, Beta(0.30, k = 4) (field small bets ~0.3)."""
        return (self.ra_air + 0.30 * 4.0) / (self.ra_n + 4.0)

    def tbus(self, prior):
        """v11: how often he 3-bets OUR opens (prior = his 3-bet rate against any open)."""
        return (self.tu_r + prior * 6.0) / (self.tu_n + 6.0)


# --------------------------------------------------------------------------- the agent
class Agent:
    def __init__(self):
        self.me = 0
        self.n = 0
        self.opp = None
        self.hand_no = -1
        self.spent = 0.0
        self.hscale = 1.0               # v11.1: bank thresholds scale with hands per table (final: 5,000)
        self.S0 = 2000
        self.bd = []
        self.hole = [0, 1]
        self.hc = 0
        self.hk = 0
        self.hidx = 0

    def on_table_start(self, info):
        try:
            self.me = int(info.get("seat", 0))
            n = int(info.get("num_players", 8))
            self.n = n
            self.opp = [Opp() for _ in range(n)]
            self.S0 = int(info.get("starting_stack", 2000))
            self.hscale = max(1.0, min(5.0, float(info.get("hands", 1000) or 1000) / 1000.0))
        except Exception:
            pass

    # ----------------------------------------------------------------- entry points
    def act(self, state):
        t0 = _pc()
        try:
            out = self._act(state, t0)
        except Exception:
            out = self._safe(state)
        self.spent += _pc() - t0 + V11_OVERHEAD
        return out

    def on_hand_end(self, summary):
        try:
            self._learn(summary)
        except Exception:
            pass

    @staticmethod
    def _safe(state):
        try:
            legal = state.get("legal_actions", ())
            if "check" in legal:
                return CHECK
            if state.get("to_call", 1) <= 0.12 * state.get("pot", 0):
                return CALL
        except Exception:
            pass
        return FOLD

    def _act(self, s, t0):
        if s["hand_number"] != self.hand_no or len(s["history"]) < self.hidx:
            self._new_hand(s)
        if s["street"] == "preflop":
            self._sync(s, t0)
            return self._preflop(s)
        self.bd = [CARD[c] for c in s["board"]]
        if self.spent > 7.0 * self.hscale:
            return self._cheap(s)          # time bank nearly gone: table-only play
        self._sync(s, t0)
        return self._postflop(s, t0)

    def _new_hand(self, s):
        n = len(s["stacks"])
        if self.opp is None or len(self.opp) != n:
            self.opp = [Opp() for _ in range(n)]
        self.n = n
        self.me = me = s["seat"]
        self.hand_no = s["hand_number"]
        self.hidx = 0
        self.r_si = -1
        self.nr = 0
        self.lvl = 0
        self.rpot = 0
        self.rb = [0] * n
        self.acted = set()
        self.last_raiser = -1
        self.pfa = [0] * n
        self.prs = set()                # seats that have raised preflop this hand
        self.w3 = [0.0] * n             # v11: width of each villain's 3-bet range (share of all hands)
        self.agg = [-1, -1, -1, -1]     # v13: last raiser on each street
        self.chk = set()                # v13: seats that checked on the current street
        self.pfw = [MASS0] * n          # preflop range mass per class (ORDER_ASC)
        self.ws = [None] * n            # postflop combo weights, aligned with ctx order
        self.wst = [0] * n              # street the weights are aligned to (0 = preflop)
        self.ctx = [None, None, None, None]
        self.bd = []
        h = s["hole_cards"]
        a, b = CARD[h[0]], CARD[h[1]]
        if a > b:
            a, b = b, a
        self.hole = [a, b]
        self.hc = CLS[KID[a * 52 + b]]
        self.hk = a * 52 + b
        hist = s["history"]
        self.sbs = hist[0]["seat"] if hist else -1
        self.bbs = hist[1]["seat"] if len(hist) > 1 else -1
        if s["street"] == "preflop":
            self.S0 = s["stacks"][me] + s["bets"][me]
        self.shv = 0.4 * self.S0
        self.shc = 0.33 * self.S0

    def _u(self, salt):
        """Deterministic pseudo-random number in [0, 1) for mixed frequencies."""
        x = (self.hand_no * 2654435761 + self.hk * 40503 + salt * 977) & 0xFFFFFFFF
        x ^= x >> 15
        x = (x * 2246822519) & 0xFFFFFFFF
        x ^= x >> 13
        return x / 4294967296.0

    # ----------------------------------------------------------------- history replay (live)
    def _sync(self, s, t0):
        hist = s["history"]
        nh = len(hist)
        i = self.hidx
        folded = s["folded"]
        me = self.me
        self._mw = sum(1 for x in folded if not x) > 2      # v11: multiway at this decision
        while i < nh:
            e = hist[i]
            i += 1
            a = e["action"]
            seat = e["seat"]
            si = STREET_IDX[e["street"]]
            if si != self.r_si:
                self.r_si = si
                self.rb = [0] * self.n
                self.lvl = 0
                self.acted = set()
                self.chk = set()
            amt = e["amount"]
            rb = self.rb
            if a == "small_blind" or a == "big_blind":
                rb[seat] = amt
                self.rpot += amt
                if amt > self.lvl:
                    self.lvl = amt
                continue
            mine = rb[seat]
            tc = self.lvl - mine
            if seat != me and not folded[seat]:
                if si == 0:
                    self._pf_upd(seat, a, amt, tc)
                else:
                    self._po_upd(seat, a, amt, tc, si, t0)
            if a == "call":
                rb[seat] = mine + amt
                self.rpot += amt
                self.acted.add(seat)
            elif a == "raise":
                self.rpot += amt - mine
                rb[seat] = amt
                self.lvl = amt
                if si == 0:
                    self.nr += 1
                    self.prs.add(seat)
                self.acted = {seat}
                self.last_raiser = seat
                self.agg[si] = seat
            else:
                self.acted.add(seat)
                if a == "check":
                    self.chk.add(seat)
            if si == 0:
                self.pfa[seat] += 1
        self.hidx = nh

    # ----------------------------------------------------------------- layer 3: bridge, preflop
    def _pf_upd(self, v, a, amt, tc):
        """Update villain v's preflop range for one action using his measured frequencies."""
        if a == "fold":
            return
        o = self.opp[v]
        m = self.pfw[v]
        nr = self.nr
        first = self.pfa[v] == 0
        frac = sum(m) / 1326.0
        if frac <= 1e-6:
            return
        if a == "raise":
            if amt >= self.shv:
                p = 0.055 + o.g * ((o.fd_sh + 0.4) / (o.fd_n + 12.4) - 0.055)
                q = p / frac
                u = _uninf(o.sd_s_n, o.sd_s_sum, p)
                if V11_JAM_FIX and nr >= 1 and self.prs <= {v, self.me}:
                    # v11: a jam over OUR raise (no third raiser) is a re-raise, not an open shove:
                    # use his re-raise rate here (elsewhere keep v10's model)
                    if v in self.prs:
                        # he raised earlier and now re-jams: never model that as 'AA only'
                        qc = o.f(o.d3_r, o.d3_n, 0.17, 6.0) if nr == 2 else o.f(o.d4_r, o.d4_n, 0.50, 5.0)
                        q = max(q, min(0.6, qc), 0.25)
                    else:
                        # cold jam (3-bet or squeeze jam): about the top half of his re-raising range
                        qc = o.f(o.fr_r, o.fr_n, 0.06, 10.0) if nr == 1 else o.f(o.f3_r, o.f3_n, 0.035, 8.0)
                        if not first:
                            qc = min(0.5, qc / frac)
                        q = max(q, min(0.25, 0.5 * qc))
            elif nr == 0:
                nb = self.n - len(self.acted) - 1
                q = o.f(o.uo_r, o.uo_n, 0.17, 10.0) * POSF[nb if 0 <= nb < 8 else 4]
                u = _uninf(o.sd_r_n, o.sd_r_sum, q)
            elif nr == 1:
                p3 = o.f(o.fr_r, o.fr_n, 0.06, 10.0)
                if V11_3BET_DEF and self.last_raiser == self.me:
                    p3 = max(p3, o.tbus(p3))    # v11: his 3-bet rate against OUR opens
                q = p3 if first else min(0.5, p3 / frac)
                self.w3[v] = q * frac           # v11: before the 0.015 floor and the showdown u-mixing
                u = _uninf(o.sd_r_n, o.sd_r_sum, q) * 0.7
            else:
                if v not in self.prs:
                    q = o.f(o.f3_r, o.f3_n, 0.035, 8.0)
                    if not first:
                        q = min(0.5, q / frac)
                elif nr == 2:
                    q = o.f(o.d3_r, o.d3_n, 0.17, 6.0)
                else:
                    q = o.f(o.d4_r, o.d4_n, 0.50, 5.0)
                u = _uninf(o.sd_r_n, o.sd_r_sum, q) * 0.5
            q = min(1.0, max(0.012, q))
            if q >= 0.97:
                return
            t = _top(q, 0.02 + 0.12 * q, 0.015)
            if u > 0.02:
                t = [(1.0 - u) * x + u for x in t]
        elif a == "call":
            if tc >= self.shc:
                if v in self.prs:
                    q = o.callraised(frac)
                else:
                    q = min(1.0, max(0.03, o.callshove() / frac))
                if q >= 0.97:
                    return
                t = _top(q, 0.02 + 0.12 * q, 0.01)
            elif nr == 0:
                nb = self.n - len(self.acted) - 1
                pr = min(0.95, o.f(o.uo_r, o.uo_n, 0.17, 10.0) * POSF[nb if 0 <= nb < 8 else 4])
                pl = o.f(o.uo_l, o.uo_n, 0.10, 10.0)
                hi = min(1.0, pr + pl + 0.04)
                if hi >= 0.97 and pr < 0.03:
                    return
                t = _top(hi, 0.03 + 0.1 * hi, 0.02)
                if pr >= 0.03:
                    t2 = _top(pr, 0.02 + 0.1 * pr)
                    t = [x * (1.0 - 0.8 * y) for x, y in zip(t, t2)]
            elif nr == 1:
                pc = o.f(o.fr_c, o.fr_n, 0.14, 10.0)
                p3 = o.f(o.fr_r, o.fr_n, 0.06, 10.0)
                if v == self.bbs:
                    pc = min(0.95, pc * 1.7)
                if first:
                    hi = min(1.0, pc + p3 + 0.03)
                else:
                    hi = min(1.0, max(0.4, (pc + p3) / frac))
                    p3 = min(0.5, p3 / frac)
                if hi >= 0.97 and p3 < 0.03:
                    return
                t = _top(hi, 0.03 + 0.1 * hi, 0.02)
                if p3 >= 0.02:
                    t2 = _top(p3, 0.02 + 0.1 * p3)
                    t = [x * (1.0 - 0.7 * y) for x, y in zip(t, t2)]
            else:
                if v not in self.prs:
                    hi = max(0.02, o.f(o.f3_c + o.f3_r, o.f3_n, 0.075, 8.0))
                    if not first:
                        hi = min(1.0, max(0.25, hi / frac))
                elif nr == 2:
                    hi = min(1.0, o.f(o.d3_c + o.d3_r, o.d3_n, 0.47, 6.0))
                else:
                    hi = min(1.0, o.f(o.d4_c + o.d4_r, o.d4_n, 0.69, 5.0))
                if hi >= 0.97:
                    return
                t = _top(hi, 0.03 + 0.1 * hi, 0.02)
        else:  # big blind checks his option: no top of range
            pr = o.f(o.uo_r, o.uo_n, 0.17, 10.0) * 0.6
            if pr < 0.04:
                return
            t = [1.0 - 0.9 * x for x in _top(min(0.95, pr), 0.02 + 0.1 * pr)]
        self.pfw[v] = _apply(m, t)

    # ----------------------------------------------------------------- layer 3: bridge, postflop
    def _po_upd(self, v, a, amt, tc, si, t0):
        """Likelihood update of villain v's combo weights for one postflop action."""
        if a == "fold" or _pc() - t0 > V11_UPD_DL:
            return
        ctx = self.ctx[si]
        if ctx is None:
            if si + 2 > len(self.bd) or si != len(self.bd) - 2:
                return
            ctx = self._mkctx(si)
        o = self.opp[v]
        if tc <= 0:
            beta = o.f(o.cb_b[si], o.cb_n[si], BET_P[si], 8.0)
            if a == "check":
                if beta < 0.12:
                    return
            elif beta > 0.9:
                return
            bl = BLUFF_SH[si]
            if V11_HONESTY and si == 3:
                bl = max(0.06, min(0.5, o.air()))       # v11: this villain's measured river air share
            elif V13_RIVER_BLSH and si == 3 and a == "raise":
                fr_b = amt / self.rpot if self.rpot > 0 else 1.0
                bl = 0.34 if fr_b <= 0.45 else (0.26 if fr_b <= 0.6 else 0.20)   # v13: measured by size
            vq = beta * (1.0 - bl)
            if a == "raise":
                # big-bet signal: far above this villain's usual size -> stronger range
                avg = (o.bs_sum + 0.6 * 4.0) / (o.bs_n + 4.0)
                avg = 0.6 + o.g * (avg - 0.6)
                pot0 = self.rpot
                rel = (amt / pot0) / max(0.2, avg) if pot0 > 0 else 1.0
                if rel > 1.4:
                    vq *= max(0.45, rel ** -0.8)
                elif rel < 0.5:
                    vq = min(0.95, vq * 1.25)
            eps = min(1.0, beta * bl / max(0.05, 1.0 - vq))
            t = _top(vq, 0.08, eps)
            if a == "check":
                t = [max(0.1, 1.0 - x) for x in t]
        else:
            b = _bucket(tc, self.rpot)
            if a == "raise":
                r = o.raisep(b)
                vq = r * 0.8
                t = _top(vq, 0.06, min(1.0, r * 0.2 / max(0.05, 1.0 - vq)))
            elif a == "call":
                f = o.foldp(b)
                if f < 0.08:
                    return
                r = o.raisep(b)
                t = _top(1.0 - f, 0.08, 0.04)
                if r > 0.02:
                    t2 = _top(r * 0.8, 0.06)
                    t = [x * (1.0 - 0.6 * y) for x, y in zip(t, t2)]
            else:
                return
        if V11_TFL > 0.0:
            k_ = V11_TFL if not getattr(self, "_mw", False) else 0.5 * V11_TFL   # calibrated heads-up; half multiway
            if V11_HONESTY and si == 3 and o.air() < 0.12:
                k_ *= 0.5                       # v11: measured honest river bettor: trust his bets more
            t = [k_ + (1.0 - k_) * x for x in t]
        self._to_street(v, si)
        self.ws[v] = _apply(self.ws[v], t)

    def _to_street(self, v, si):
        """Re-align villain v's weights with the combo order of street si."""
        cur = self.wst[v]
        if cur == si and self.ws[v] is not None:
            return
        ok = self.ctx[si][1]
        if cur == 0 or self.ws[v] is None or self.ctx[cur] is None:
            m = self.pfw[v]
            cw = [0.0] * 169
            for pos, c in enumerate(ORDER_ASC):
                cw[c] = m[pos] * INVC[c]
            ws = [cw[CLS[k]] for k in ok]
        else:
            d = dict(zip(self.ctx[cur][1], self.ws[v]))
            ws = [d[k] for k in ok]
        self.ws[v] = ws
        self.wst[v] = si

    # ----------------------------------------------------------------- layer 4: street context
    def _mkctx(self, si):
        """All villain combos on this board sorted weakest -> strongest (draws promoted)."""
        bd = self.bd[:si + 2]
        used = BIT[self.hole[0]] | BIT[self.hole[1]]
        brk = 0
        bm = 0
        bsc = [0, 0, 0, 0]
        bsm = [0, 0, 0, 0]
        for c in bd:
            used |= BIT[c]
            brk += RK[c]
            s_ = c & 3
            bsc[s_] += 1
            bsm[s_] |= 1 << (c >> 2)
            bm |= 1 << (c >> 2)
        prev = self.ctx[si - 1] if si > 1 else None
        base = prev[1] if prev else ALLK
        live = [k for k in base if not CM[k] & used]
        over = {}
        for s_ in range(4):
            bc = bsc[s_]
            if bc >= 3:
                m0 = bsm[s_]
                if bc == 3:
                    for k in SUITED[s_]:
                        over[k] = FL[m0 | CSM[k][s_]]
                else:
                    for k in live:
                        f = FL[m0 | CSM[k][s_]]
                        if f:
                            over[k] = f
        og = over.get
        if si < 3:
            # draws count as continues: lift them to a made-hand-equivalent strength
            rs = sorted({c >> 2 for c in bd}, reverse=True)
            b1 = rs[0]
            b2 = rs[1] if len(rs) > 1 else rs[0]
            t3 = (1 << 20) | (b1 << 16) | (12 << 12)
            t2 = (1 << 20) | (b2 << 16) | (12 << 12)
            t1 = (1 << 20) | (rs[-1] << 16)
            for s_ in range(4):
                bc = bsc[s_]
                if bc == 2:
                    for k in SUITED[s_]:
                        over[k] = t2
                elif bc == 3:
                    m0 = bsm[s_]
                    for r in (12, 11, 10):
                        if not (m0 >> r) & 1:
                            for k in CARD_COMBOS[r * 4 + s_]:
                                if og(k, 0) < t2:
                                    over[k] = t2
            if STR[bm] < 0:
                sdb = SD[bm]
                for bits, lst in RPAIRS:
                    m2 = bm | bits
                    if m2 != bm and STR[m2] < 0:
                        d = SD[m2]
                        if d > sdb:
                            if d >= 2:
                                for k in lst:
                                    x = og(k, 0)
                                    if x == t2:
                                        over[k] = t3
                                    elif x < t2:
                                        over[k] = t2
                            else:
                                for k in lst:
                                    if og(k, 0) < t1:
                                        over[k] = t1
        nf = NF
        if over:
            enc = [(max(nf[brk + RKS[k]], og(k, 0)) << 11) | k for k in live]
        else:
            enc = [(nf[brk + RKS[k]] << 11) | k for k in live]
        enc.sort()
        ok = [e & 2047 for e in enc]
        ctx = (enc, ok, len(ok))
        self.ctx[si] = ctx
        return ctx

    # ----------------------------------------------------------------- layer 4: Monte Carlo
    def _mc(self, accs, tots, ok, n_s, dl):
        """Sample (villain combos, runout); per villain: bucketed counts/wins; overall wins."""
        bd = self.bd
        hole = self.hole
        b_rk = b_sk = 0
        b_sm = [0, 0, 0, 0]
        for c in bd:
            b_rk += RK[c]
            b_sk += SK[c]
            b_sm[c & 3] |= 1 << (c >> 2)
        h_rk = b_rk
        h_sk = b_sk
        h_sm = b_sm[:]
        used = 0
        for c in hole:
            h_rk += RK[c]
            h_sk += SK[c]
            h_sm[c & 3] |= 1 << (c >> 2)
            used |= BIT[c]
        if len(bd) == 3:
            runs = _choices(ok, k=n_s)
            ma, rka, ska, sma = CM, RKS, SKS, CSM
        else:
            for c in bd:
                used |= BIT[c]
            deck = [c for c in range(52) if not used & BIT[c]]
            runs = _choices(deck, k=n_s)
            ma, rka, ska, sma = BIT, RK, SK, CARD_SM
        nv = len(accs)
        rng_n = range(len(ok))
        fs_t = FS
        fl = FL
        nf = NF
        cm = CM
        rks = RKS
        sks = SKS
        csm = CSM
        cnts = [[0] * NBK for _ in range(nv)]
        wins = [[0.0] * NBK for _ in range(nv)]
        tot_n = 0
        tot_w = 0.0
        it = 0
        if nv == 1:
            acc = accs[0]
            sc = NBK / tots[0] * 0.999999
            cnt = cnts[0]
            win = wins[0]
            poss = _choices(rng_n, cum_weights=acc, k=n_s)
            for j, rk in zip(poss, runs):
                it += 1
                if not it & 63 and _pc() > dl:
                    break
                vk = ok[j]
                if cm[vk] & ma[rk]:
                    continue
                rr = rka[rk]
                rs = ska[rk]
                sm = sma[rk]
                f = fs_t[h_sk + rs]
                hs = fl[h_sm[f] | sm[f]] if f >= 0 else nf[h_rk + rr]
                f = fs_t[b_sk + rs + sks[vk]]
                vs = fl[b_sm[f] | sm[f] | csm[vk][f]] if f >= 0 else nf[b_rk + rr + rks[vk]]
                b = int(acc[j] * sc)
                cnt[b] += 1
                if hs > vs:
                    win[b] += 1.0
                    tot_w += 1.0
                elif hs == vs:
                    win[b] += 0.5
                    tot_w += 0.5
                tot_n += 1
            return cnts, wins, tot_n, tot_w
        poss = [_choices(rng_n, cum_weights=acc, k=n_s) for acc in accs]
        scs = [NBK / t * 0.999999 for t in tots]
        vr = range(nv)
        vks = [0] * nv
        for t in range(n_s):
            it += 1
            if not it & 31 and _pc() > dl:
                break
            rk = runs[t]
            um = ma[rk]
            bad = False
            for vi in vr:
                vk = ok[poss[vi][t]]
                x = cm[vk]
                if x & um:
                    bad = True
                    break
                um |= x
                vks[vi] = vk
            if bad:
                continue
            rr = rka[rk]
            rs = ska[rk]
            sm = sma[rk]
            f = fs_t[h_sk + rs]
            hs = fl[h_sm[f] | sm[f]] if f >= 0 else nf[h_rk + rr]
            best = 0
            for vi in vr:
                vk = vks[vi]
                f = fs_t[b_sk + rs + sks[vk]]
                vs = fl[b_sm[f] | sm[f] | csm[vk][f]] if f >= 0 else nf[b_rk + rr + rks[vk]]
                b = int(accs[vi][poss[vi][t]] * scs[vi])
                cnts[vi][b] += 1
                if hs > vs:
                    wins[vi][b] += 1.0
                elif hs == vs:
                    wins[vi][b] += 0.5
                if vs > best:
                    best = vs
            tot_n += 1
            if hs > best:
                tot_w += 1.0
            elif hs == best:
                tot_w += 0.5
        return cnts, wins, tot_n, tot_w

    # ----------------------------------------------------------------- layer 1: postflop EV
    def _postflop(self, s, t0):
        me = self.me
        n = self.n
        bd = self.bd
        si = len(bd) - 2
        folded = s["folded"]
        stacks = s["stacks"]
        bets = s["bets"]
        pot = s["pot"]
        tc = s["to_call"]
        legal = s["legal_actions"]
        vill = [v for v in range(n) if v != me and not folded[v]]
        if not vill:
            return CHECK if "check" in legal else CALL
        ctx = self.ctx[si] or self._mkctx(si)
        enc, ok, n_c = ctx
        dropped = 0
        if len(vill) > 4:
            vill.sort(key=lambda v: -bets[v])
            dropped = len(vill) - 4
            vill = vill[:4]
        hs = ev7(self.hole + bd)
        lo = bisect_left(enc, hs << 11)
        uh = lo / n_c
        accs = []
        tots = []
        for v in vill:
            self._to_street(v, si)
            acc = list(accumulate(self.ws[v]))
            if acc[-1] <= 1e-9:
                self.ws[v] = [1.0] * n_c
                acc = list(accumulate(self.ws[v]))
            accs.append(acc)
            tots.append(acc[-1])
        nv = len(vill)
        cbs = []
        wbs = []
        eqs = []
        eq_all = 1.0
        exact = si == 3 or _pc() - t0 > V11_MC_SKIP  # v11: already 7 ms in (slow server): skip Monte Carlo
        if not exact:
            n_s = (440, 280, 190, 140)[nv - 1]
            if self.spent > 4.0 * self.hscale:
                n_s = n_s // 2 if self.spent < 5.5 * self.hscale else n_s // 5
            cnts, wins, tot_n, tot_w = self._mc(accs, tots, ok, n_s, t0 + V11_MC_DL)
            if tot_n >= 24:
                eq_all = tot_w / tot_n
                inv = 1.0 / tot_n
                for vi in range(nv):
                    cnt = cnts[vi]
                    win = wins[vi]
                    ev_ = sum(win) * inv
                    eqs.append(ev_)
                    cbs.append([c * inv for c in cnt])
                    wbs.append([(w + ev_) / (c + 1.0) for w, c in zip(win, cnt)])
            else:
                exact = True       # ran out of time: fall back to current-strength percentiles
        if exact:
            hi = bisect_left(enc, (hs + 1) << 11)
            for acc, tot in zip(accs, tots):
                below = acc[lo - 1] if lo else 0.0
                tie = (acc[hi - 1] if hi else 0.0) - below
                hp = (below + 0.5 * tie) / tot
                eqs.append(hp)
                eq_all *= hp
                cbs.append(UNI)
                wbs.append([min(1.0, max(0.0, hp * NBK - b)) for b in range(NBK)])
        if dropped:
            eq_all *= 0.8 ** dropped
        if uh > 0.80:
            # absolute-strength floor: stacked likelihood updates must not talk us out of near-nut hands
            fl_ = (uh - 0.80) * 3.1
            if nv > 1:
                fl_ *= 0.8 ** (nv - 1)
            if eq_all < fl_:
                eq_all = fl_

        s0 = self.S0
        mybet = bets[me]
        mystack = stacks[me]
        btn = s["button"]
        myidx = (me - btn - 1) % n
        ip = True
        for v in vill:
            if stacks[v] > 0 and (v - btn - 1) % n > myidx:
                ip = False
        spr = mystack / pot if pot > 0 else 10.0
        commit_adj = (1.0 / (1.0 + exp(-(spr - 4.0) / 1.5)) - 0.3) * 0.05     # SPR-aware commitment

        # ---- passive option
        if tc <= 0:
            if si == 3:
                rk_ = 1.0 if ip else 0.95
            else:
                rk_ = 1.0 if ip else 0.92
            ev_pass = rk_ * eq_all * pot
            passive = CHECK
        else:
            rc = 1.0 if si == 3 else (0.96 if ip else 0.90)
            if V11_FLOP_RZ < 1.0 and si == 1 and self._weak_flop(hs, bd):
                rc *= V11_FLOP_RZ               # v11: weak pairs / air without a strong draw realise ~0.65-0.75
            fin = pot + tc
            ev_call = rc * eq_all * fin - tc
            risk = tc / s0
            if risk > 0.1:
                ev_call -= VPEN * risk * risk * fin
            if tc >= 0.5 * mystack:
                ev_call -= commit_adj * fin
            if si == 3 and nv == 1 and ev_call <= 0 and risk < 0.3:
                # MDF floor against unknown opponents: do not be auto-bluffable on the river
                o = self.opp[vill[0]]
                mdf = (pot - tc) / pot if pot > 0 else 0.5
                if (o.g < 0.5 or (V11_MDF_ALWAYS and s.get("raises_this_street", 0) <= 1
                                  and (not V11_HONESTY or o.air() >= 0.15))) and uh >= 1.0 - 0.45 * mdf:
                    ev_call = 0.01
            if (V11_RIVER_CATCH and si == 3 and nv == 1 and ev_call <= 0 and s.get("raises_this_street", 0) <= 1
                    and tc <= 0.6 * max(1, pot - tc)
                    and (self._tp_plus(hs, bd)
                         or (V13_WEAKPAIR and tc <= 0.55 * max(1, pot - tc) and uh >= 0.57 and tc < 0.3 * self.S0
                             and self._hole_pair(hs, bd)
                             and (self.opp[vill[0]].ra_n < 4 or self.opp[vill[0]].air2() >= 0.12)))):
                o = self.opp[vill[0]]
                if not V11_HONESTY or o.air() >= 0.15:
                    ev_call = 0.01              # v11: small river bets in this field are 26-37% air
            agg_ = 0.0
            for v in vill:
                o_ = self.opp[v]
                if bets[v] >= max(bets) and o_.g >= 0.6:
                    nn = o_.cb_n[1] + o_.cb_n[2] + o_.cb_n[3]
                    if nn >= 8:
                        agg_ = (o_.cb_b[1] + o_.cb_b[2] + o_.cb_b[3]) / nn
            gl = 0.12 if agg_ >= 0.75 else 0.0
            if (ev_call > 0 and tc >= 0.3 * s0 and uh < (0.90 if si == 3 else 0.84) - gl and eq_all < 0.75 - gl
                    and tc >= V11_PRICE_GUARD * fin):
                ev_call = -1.0              # stack-off guard (v11: only when the price is high)
            if ev_call > 0 and tc >= 0.15 * s0 and s.get("raises_this_street", 0) >= 2 and tc >= V11_PRICE_GUARD * fin:
                cat_ = hs >> 20
                if cat_ == 2 and len({c >> 2 for c in bd}) < len(bd):
                    cat_ = 1                # two pair made by a paired board is really one pair
                if cat_ <= 1 and eq_all < 0.75:
                    ev_call = -1.0          # a big raise means a big hand: one pair folds
            if ev_call > 0:
                ev_pass = ev_call
                passive = CALL
            else:
                ev_pass = 0.0
                passive = FOLD
        if "raise" not in legal:
            return passive
        if _pc() - t0 > V11_HARD_DL:
            return passive                  # v11: time cap; the bet/raise search is the slowest remaining part

        # ---- aggressive options
        mn = s["min_raise_to"]
        mx = s["max_raise_to"]
        lvl = max(bets)
        base = pot + tc
        xs = []
        for f in ((0.5, 1.0) if tc > 0 else (0.33, 0.66, 1.0, 1.7)):
            x = int(lvl + f * base)
            x = mn if x < mn else (mx if x > mx else x)
            if x not in xs:
                xs.append(x)
        if mystack <= 3.2 * base and mx not in xs:
            xs.append(mx)
        capx = 0
        act_i = []
        eq_ai = 1.0
        n_ai = 0
        for vi, v in enumerate(vill):
            if stacks[v] > 0:
                act_i.append(vi)
                if bets[v] + stacks[v] > capx:
                    capx = bets[v] + stacks[v]
            else:
                eq_ai *= eqs[vi]
                n_ai += 1
        if not act_i:
            return passive
        opp = self.opp
        tau_inv = 1.0 / 0.12
        rb_ = 0.97 if ip else 0.93
        best_ev = -1e18
        best_x = 0
        cap = (0.0, 0.55, 0.38, 0.28)[si]
        line_ = ""
        if V13_LINE_BLUFF and nv == 1 and tc <= 0 and si >= 2:
            v_ = vill[0]
            prev_ = self.agg[si - 1]
            if self.r_si == si and v_ in self.chk:    # v13.1: checks from a previous street do not count
                line_ = "gaveup" if prev_ == v_ else ("xthru_ip" if prev_ < 0 else "barrel_ip")
            else:
                line_ = "xthru_oop" if prev_ < 0 else ("barrel_oop" if prev_ == me else "donk")
            cap = {"gaveup": 0.70, "xthru_ip": (0.80 if si == 3 else 0.70), "xthru_oop": (0.80 if si == 3 else 0.70),
                   "barrel_ip": 0.45, "barrel_oop": 0.38, "donk": 0.38}[line_]
        if V12_HU_BLUFF and not line_ and nv == 1 and tc <= 0 and si >= 2:
            cap = 0.45                      # v12 (only when the v13 line-aware cap is off)
        sticky_ = (V12_VALUE and nv == 1 and tc <= 0 and self.opp[vill[0]].g >= 0.6
                   and self.opp[vill[0]].foldp(2) <= 0.50)
        if nv >= 2:
            cap *= 0.4
        if tc > 0:
            cap *= 0.6
        u = self._u(si * 7 + s.get("raises_this_street", 0))
        u2 = self._u(500 + si * 7 + s.get("raises_this_street", 0))     # v18: independent draw (out-of-plan aggression)
        mixa_ = V18_AIR_P > 0 and tc <= 0 and nv <= 2 and u2 <= V18_AIR_P
        small_ = (V18_RAISE_P > 0 and tc > 0 and nv == 1 and si < 3 and s.get("raises_this_street", 0) <= 1
                  and tc <= 0.4 * max(1, pot - tc))
        mixr_ = small_ and u2 <= V18_RAISE_P
        gmin = 1.0
        for v in vill:
            if opp[v].g < gmin:
                gmin = opp[v].g
        cap *= 0.55 + 0.45 * gmin          # dynamic gating: bluff less until the table is known
        ipr_ = False
        if (V13_IP_RAISE and tc > 0 and si in (1, 2) and ip and nv == 1 and me not in self.chk
                and s.get("raises_this_street", 0) == 1 and vill[0] == self.last_raiser):
            o_ = opp[vill[0]]
            if o_.br_n >= 5 and o_.foldraise() >= 0.75 and eq_all >= 0.20 and u <= 0.5:
                ipr_ = True                     # v13: he led and folds >= 75% when raised
        lr_ = self.last_raiser
        for x in xs:
            xe = x if x < capx else capx
            inv = xe - mybet
            if inv <= 0:
                continue
            pot_incl = pot + inv
            rs = []
            pen = 0.0
            cut = 0.0
            for vi in act_i:
                v = vill[vi]
                add = xe - bets[v]
                if add > stacks[v]:
                    add = stacks[v]
                if add <= 0:
                    continue
                # P(continue): share of his range strong enough, shifted by his measured stickiness
                b = _bucket(add, pot_incl)
                o = opp[v]
                acc = accs[vi]
                bl_ = 0.0
                cr = 0.0
                if tc > 0:
                    # we are raising: the bettor defends his bet often, everyone else folds
                    if v != lr_:
                        q = 0.10
                    elif small_:
                        q = 1.0 - o.f(o.br_f, o.br_n, 0.62, 6.0)    # v18: small leads fold 61-77% to a raise (real logs)
                    else:
                        q = 1.0 - o.foldraise()
                    rsh = 0.20
                else:
                    ub = UB[b] + (0.05 if si == 3 else 0.0)
                    qr = 1.0 - acc[int(ub * n_c)] / tots[vi]
                    qr = 0.03 if qr < 0.03 else (0.97 if qr > 0.97 else qr)
                    fm = o.foldp(b)
                    fp = FOLD_P[b]
                    z = log(qr / (1.0 - qr)) + log((1.0 - fm) / fm) - log((1.0 - fp) / fp)
                    q = 1.0 / (1.0 + exp(-z))
                    rsh = o.raisep(b) / (q if q > 0.15 else 0.15)
                    if rsh > 0.5:
                        rsh = 0.5
                    bl_ = V12_FOLD_BLEND
                    cr = 1.0 - fm                   # v12: his measured continue rate at this size
                thr = 1.0 - q
                thr_c = (1.0 - ((1.0 - bl_) * q + bl_ * cr)) if bl_ else thr
                ct_ = bisect_left(acc, thr_c * tots[vi]) / n_c     # absolute strength where he starts calling
                if ct_ > cut:
                    cut = ct_
                qq = 0.0
                ee = 0.0
                cb = cbs[vi]
                wb = wbs[vi]
                for k in range(NBK):
                    c = ((k + 0.5) * _INBK - thr) * tau_inv + 0.5
                    if c < 0.0:
                        c = 0.0
                    elif c > 1.0:
                        c = 1.0
                    if bl_:
                        c = (1.0 - bl_) * c + bl_ * cr     # v12: part of his calls ignore his hand strength
                    if c <= 0.0:
                        continue
                    m = cb[k] * c
                    qq += m
                    ee += m * wb[k]
                if qq < 1e-6:
                    rs.append((0.0, wb[NBK - 1], add))
                else:
                    qq = qq if qq < 1.0 else 1.0
                    ei_ = ee / qq
                    rs.append((qq, ei_, add))
                    # raise risk: when he raises our bet we usually have to give the pot up
                    et = wb[NBK - 1]
                    w_ = 1.0 if et < 0.35 else (0.0 if et > 0.60 else (0.60 - et) * 4.0)
                    pen += qq * rsh * w_ * ei_ * (pot + inv + add)
            if not rs:
                continue
            rs.sort(reverse=True)
            extra = rs[3:]
            rs = rs[:3]
            k = len(rs)
            ev = 0.0
            p_call = 0.0
            e_call = 0.0
            for mask in range(1 << k):
                p = 1.0
                e = eq_ai
                adds = 0
                for i in range(k):
                    q, ei, ad = rs[i]
                    if (mask >> i) & 1:
                        p *= q
                        e *= ei
                        adds += ad
                    else:
                        p *= 1.0 - q
                if mask == 0:
                    ev += p * (pot if not n_ai else e * pot)
                else:
                    er = e if (si == 3 or e >= 0.6) else e * rb_
                    ev += p * (er * (pot + inv + adds) - inv)
                    p_call += p
                    e_call += p * e
            for q, ei, ad in extra:
                ev -= q * inv * 0.6
            ev -= pen
            e_c = e_call / p_call if p_call > 1e-9 else 1.0
            fr_ = (x - lvl) / base if base > 0 else 1.0
            if tc > 0 and inv >= 0.45 * s0 and uh < 0.95 and spr > 1.2:
                continue                    # raising for stacks postflop: near-nut hands only
            if inv >= 0.3 * s0 and uh < (0.76 if sticky_ else 0.84) and eq_all < 0.75:
                continue                    # no big bets or raises with hands that cannot stand a call
            weak = uh < cut and (si == 3 or eq_all < 0.5)    # we do not beat the hands that call
            if fr_ > 1.05 and (e_c < 0.5 or weak or uh < (0.80 if V12_VALUE else 0.9)):
                continue                    # overbets and big raises are for value only
            risk = inv / s0
            if risk > 0.1:
                ev -= VPEN * risk * risk * (pot + 2 * inv) * p_call
            if inv >= 0.5 * mystack:
                ev -= commit_adj * (pot + 2 * inv) * p_call
            # bluff-frequency cap: pure bluffs only a capped share of the time
            if (tc > 0 and e_c < 0.5 and not ipr_ and not mixr_
                    and not (si < 3 and uh < 0.5 and eq_all >= 0.33 and u <= 0.20)):
                continue
            if weak or (e_c < (0.35 if si == 3 else 0.40) and eq_all < 0.45):
                if fr_ > (1.05 if (line_ in ("gaveup", "xthru_ip", "xthru_oop")
                                   or (V12_HU_BLUFF and nv == 1 and tc <= 0 and line_ not in ("barrel_oop", "donk")))
                          else 0.75):
                    continue                # bluffs stay small (v13: up to pot into capped ranges)
                if line_ in ("barrel_oop", "donk") and fr_ < 0.6:
                    continue                # v13: small OOP barrels / leads get ~15% folds
                c_ = cap
                if tc > 0:
                    if ipr_:
                        c_ = max(c_, 0.5)   # v13: raise-folder (u <= 0.5 already checked)
                    elif mixr_:
                        c_ = 1.0            # v18: random bluff-raise of a small lead
                    elif eq_all < 0.33 or u > 0.20:
                        continue            # bluff-raise only as a rare semi-bluff with real equity
                elif si < 3 and eq_all >= 0.30:
                    c_ = max(c_, 0.60)
                if u > c_ and not mixa_:
                    continue                # v18: mixa_ lets a capped air bluff through (still needs EV > check)
            if ev > best_ev:
                best_ev = ev
                best_x = x
        margin = 0.03 * pot + (0.05 * pot if tc > 0 else 0.0)
        if best_x and best_ev > ev_pass + margin:
            return {"action": "raise", "amount": int(best_x)}
        if (V18_THIN_P > 0 and tc <= 0 and nv <= 2 and best_x and best_ev >= ev_pass - V18_TOL * pot
                and self._u(700 + si) <= V18_THIN_P):
            return {"action": "raise", "amount": int(best_x)}     # v18: near-indifferent: bet instead of checking
        return passive

    def _weak_flop(self, hs, bd):
        """v11: weak pair or air on the flop without a flush draw or an open-ended straight draw."""
        cat = hs >> 20
        if cat >= 2:
            return False
        h0, h1 = self.hole
        hr = (h0 >> 2, h1 >> 2)
        brs = [c >> 2 for c in bd]
        if cat == 1:
            pr = (hs >> 16) & 15
            if pr in hr and pr >= max(brs):
                return False                # top pair or overpair
        cards = [h0, h1] + list(bd)
        for s_ in {h0 & 3, h1 & 3}:
            if sum(1 for c in cards if c & 3 == s_) >= 4:
                return False                # flush draw
        pos = set()
        for r_ in set(hr) | set(brs):
            pos.add(r_ + 1)
            if r_ == 12:
                pos.add(0)
        hpos = set(r_ + 1 for r_ in hr)
        if 12 in hr:
            hpos.add(0)
        outs = set()
        for lo in range(10):
            win = set(range(lo, lo + 5))
            have = win & pos
            if len(have) == 4 and have & hpos:
                miss = (win - pos).pop()
                outs.add(13 if miss == 0 else miss)
        return len(outs) < 2                # an open-ender (2+ completing ranks) is not weak

    def _hole_pair(self, hs, bd):
        """v13: at least a pair that uses a hole card (any pocket pair counts)."""
        if (hs >> 20) < 1 or hs <= ev7(list(bd)):
            return False                    # no pair, or the board plays (we can only split)
        h0, h1 = self.hole
        hr0, hr1 = h0 >> 2, h1 >> 2
        if hr0 == hr1:
            return True
        brs = [c >> 2 for c in bd]
        return hr0 in brs or hr1 in brs

    def _tp_plus(self, hs, bd):
        """v11: top pair or better that uses a hole card (overpair, set, trips, two pair, straight+)."""
        cat = hs >> 20
        h0, h1 = self.hole
        hr = (h0 >> 2, h1 >> 2)
        brs = [c >> 2 for c in bd]
        if cat >= 4:
            return hs > ev7(list(bd))       # our cards improve a made straight or better
        if hr[0] == hr[1]:
            return hr[0] > max(brs) or hr[0] in brs
        hits = [r_ for r_ in hr if r_ in brs]
        if not hits:
            return False
        return max(hits) == max(brs) or len(hits) == 2 or any(brs.count(r_) >= 2 for r_ in hits)

    def _cheap(self, s):
        """Table-only postflop play when the time bank is nearly spent."""
        legal = s["legal_actions"]
        cat = ev7(self.hole + self.bd) >> 20
        tc = s["to_call"]
        pot = s["pot"]
        if tc <= 0:
            if cat >= 2 and "raise" in legal:
                x = int(max(s["bets"]) + 0.66 * pot)
                return {"action": "raise", "amount": max(s["min_raise_to"], min(s["max_raise_to"], x))}
            return CHECK
        if cat >= 3 or (cat >= 2 and tc <= pot) or (cat >= 1 and tc <= 0.3 * pot):
            return CALL
        return FOLD

    # ----------------------------------------------------------------- layer 1: preflop
    def _rz(self, hc, ip, eq):
        """Equity realisation of a hand class when calling preflop."""
        i, j = divmod(hc, 13)
        r = 0.92 if ip else 0.80
        if i == j:
            r += 0.04
        elif i < j:
            r += 0.05 + (0.03 if j - i <= 2 else 0.0)
        else:
            r -= 0.04 + (0.03 if i - j >= 4 else 0.0)
        if eq < 0.38:
            r -= 0.08
        return r

    def _preflop(self, s):
        me = self.me
        n = self.n
        legal = s["legal_actions"]
        bets = s["bets"]
        stacks = s["stacks"]
        folded = s["folded"]
        pot = s["pot"]
        tc = s["to_call"]
        bb = s["big_blind"]
        lvl = max(bets)
        s0 = stacks[me] + bets[me]
        hc = self.hc
        hp = PCT[hc]
        row = EQROW[hc]
        live = [v for v in range(n) if v != me and not folded[v]]
        can_raise = "raise" in legal
        mn = s["min_raise_to"]
        mx = s["max_raise_to"]
        nr = self.nr
        acted = self.acted
        pfw = self.pfw
        opp = self.opp
        if not live:
            return CHECK if "check" in legal else CALL

        def eqv(m):
            t = sum(m)
            return sum(map(mul, m, row)) / t if t > 1e-9 else 0.5

        # ---- facing a shove: equity vs the frequency-derived shoving range against pot odds
        if tc >= 0.33 * s0:
            eq = 1.0
            n_inv = 0
            n_beh_r = 0
            for v in live:
                if bets[v] >= lvl * 0.6 or stacks[v] == 0:
                    eq *= eqv(pfw[v])
                    n_inv += 1
                elif v in self.prs and stacks[v] > 0:
                    n_beh_r += 1                # a raiser still to act behind us
            hu_ = n_inv == 1 and n_beh_r == 0   # v11 relaxations only in clean heads-up shove spots
            beh = 0
            for v in live:
                if v not in acted and bets[v] < lvl and stacks[v] > 0:
                    beh += 1
            eq *= 1.0 - 0.012 * beh
            fin = pot + tc
            risk = tc / s0
            ev = eq * fin - tc - (V11_PF_VPEN if hu_ else VPEN) * risk * risk * fin
            known = True
            wmax = 0.0
            for v in live:
                if bets[v] >= lvl * 0.6 or stacks[v] == 0:
                    if opp[v].g < 0.9:
                        known = False
                    w_ = sum(pfw[v]) / 1326.0
                    if w_ > wmax:
                        wmax = w_
            cap_ = 0.14 if known else 0.05
            if V11_JAM_FIX and known and hu_:
                cap_ = max(0.14, min(0.35, 1.5 * wmax))     # v11: wider calls only heads-up vs measured wide jammers
            if hp > cap_ and tc > 0.5 * pot:
                return FOLD                 # stack-off guard: premium hands only unless the price is tiny
            if ev > 0 and can_raise and stacks[me] > tc * 1.15:
                return {"action": "raise", "amount": int(mx)}    # committed anyway: get it in now, never call-then-fold
            return CALL if ev > 0 else FOLD

        btn = s["button"]
        myidx = (me - btn - 1) % n

        # ---- unopened / limped pot: position range, widened or tightened by fold equity
        if nr == 0:
            behind = [v for v in live if v not in acted and stacks[v] > 0]
            limpers = [v for v in live if v in acted]
            nb = len(behind)
            nl = len(limpers)
            p = OPEN_P[nb if nb < 8 else 7]
            if nl:
                p *= 0.9 ** nl
            ratio = 1.0
            csum = 0.0
            for v in behind:
                o = opp[v]
                pr = 0.30 if v == self.bbs else 0.17
                c = o.f(o.fr_c + o.fr_r, o.fr_n, pr, 10.0)
                ratio *= (1.0 - c) / (1.0 - pr)
                csum += c
            for v in limpers:
                o = opp[v]
                csum += o.f(o.fr_c + o.fr_r, o.fr_n, 0.45, 10.0)
            p *= min(2.0, max(0.85, ratio ** 0.9))      # loose callers are no reason to stop opening for value
            if p > 0.85:
                p = 0.85
            loose = csum / max(1, nb + nl)
            if can_raise and hp <= 0.32 and mx >= 0.9 * s0:
                # value jam against opponents who call shoves far too wide
                ev_j = self._jam_ev(live, acted, row, pot, s0 - bets[me], bets, stacks, s0)
                alt = 40.0 + 2500.0 * max(0.0, PF_VS_RANDOM[hc] - 0.55)
                if ev_j > alt + 30.0:
                    return {"action": "raise", "amount": int(mx)}
            if hp <= p and can_raise:
                size = (3.0 if me == self.sbs else 2.5) * bb + bb * nl
                if loose > 0.3:
                    size *= 1.0 + min(1.2, (loose - 0.3) * 2.5)
                x = int(size)
                return {"action": "raise", "amount": max(mn, min(mx, x))}
            if tc <= 0:
                return CHECK
            if tc <= bb:
                i, j = divmod(hc, 13)
                spec = i == j or (i < j and (i == 0 or j - i <= 2))      # pairs, suited aces / connectors
                if me == self.sbs:
                    o = opp[self.bbs] if 0 <= self.bbs < n else None
                    br = o.f(o.uo_r, o.uo_n, 0.17, 10.0) if o else 0.17
                    if (hp <= 0.45 or spec) and br < 0.30:
                        return CALL                                      # complete the small blind
                elif nl >= 1 and nb <= 3 and spec and hp <= 0.55:
                    return CALL                                          # over-limp late with set-mining hands
            return FOLD

        # ---- facing a raise / 3-bet: equity vs the raiser's frequency-derived range
        rz = self.last_raiser
        if rz < 0 or rz == me or folded[rz]:
            rz = max(live, key=lambda v: bets[v])
        callers = [v for v in live if v != rz and bets[v] >= lvl]
        behind = [v for v in live if v != rz and v not in acted and stacks[v] > 0]
        eq_r = eqv(pfw[rz])
        eq = eq_r
        for v in callers:
            eq *= eqv(pfw[v])
        ip = True
        for v in live:
            if stacks[v] > 0 and (v - btn - 1) % n > myidx:
                ip = False
        rzn = self._rz(hc, ip, eq_r)
        fin = pot + tc
        ev_call = rzn * eq * fin - tc
        i, j = divmod(hc, 13)
        if tc <= 0.08 * s0:
            if i == j and i >= 3:
                ev_call += 0.45 * min(tc, 120)          # set mining
            elif i < j and j - i <= 2:
                ev_call += 0.2 * min(tc, 120)
        for v in behind:
            o = opp[v]
            ev_call -= o.f(o.fr_r, o.fr_n, 0.06, 10.0) * tc * 0.8      # squeeze risk
        risk = tc / s0
        if risk > 0.1:
            ev_call -= VPEN * risk * risk * fin
        if tc > 0 and me != self.bbs:
            ev_call -= 1.5 * bb                 # real rounds: cold calls lose, opens win; demand a margin
        hp_c3 = 0.07
        if V11_3BET_DEF and nr == 2:
            fr3 = self.w3[rz]                   # v11: measured width of HIS 3-bet range
            if fr3 >= 0.12:                     # v11: a wide 3-bettor (e.g. one who targets our opens)
                hp_c3 = min(0.20, 0.6 * fr3 + 0.04) if ip else min(0.14, 0.4 * fr3 + 0.03)
        if tc > 0 and nr >= 2 and hp > hp_c3:
            ev_call = -1.0                      # real rounds: calling 3-bets then folding the flop cost ~25 bb/100
        if tc <= 0:
            ev_call = max(ev_call, 0.0)
        elif nr >= 2 and bets[me] + tc > 0.22 * s0 and hp > 0.012:
            ev_call = -1.0                      # no flatting big re-raises: jam or fold, never call-then-fold

        best_ev = ev_call if ev_call > 0 else 0.0
        best = CALL if ev_call > 0 else (CHECK if tc <= 0 else FOLD)
        if can_raise:
            o = opp[rz]
            m = pfw[rz]
            frac = max(1e-6, sum(m) / 1326.0)
            mult = 2.3 if nr >= 2 else (3.0 if ip else 3.6)
            x = int(mult * lvl + lvl * len(callers))
            if x >= 0.45 * s0:
                x = mx
            x = max(mn, min(mx, x))
            cands = [x]
            if mx > x and mx >= 0.9 * s0 and hp <= 0.2:
                cands.append(mx)
            u = self._u(31 + nr)
            # how THIS raiser reacts to a re-raise, measured only in spots where he had raised
            if nr >= 2:
                pc = o.f(o.d4_c, o.d4_n, 0.19, 5.0)
                p4 = o.f(o.d4_r, o.d4_n, 0.50, 5.0)
                kn = o.d4_n
                kf = kn - o.d4_c - o.d4_r
            else:
                pc = o.f(o.d3_c, o.d3_n, 0.30, 6.0)
                p4 = o.f(o.d3_r, o.d3_n, 0.17, 6.0)
                kn = o.d3_n
                kf = kn - o.d3_c - o.d3_r
            sv = min(s0, bets[rz] + stacks[rz])
            dead = pot - bets[me] - bets[rz]
            blocker = i < j and (i == 0 or j - i <= 2)
            for x in cands:
                inv = x - bets[me]
                addv = min(x, bets[rz] + stacks[rz]) - bets[rz]
                if inv <= 0 or addv <= 0:
                    continue
                jam = addv >= 0.33 * s0
                b4 = V11_3BET_DEF and nr == 2 and not jam and o.g >= 0.6 and kn >= 4 and kf >= 0.65 * kn
                if (jam or nr >= 2) and not b4 and hp > (0.05 if o.g < 0.6 else max(0.05, min(0.20, 0.5 * frac))):
                    continue                # stack-off guard: big preflop pots with premium hands only
                q = min(0.97, max(0.05, o.callraised(frac))) if jam else min(0.97, pc + p4)
                eqc = eqv(_apply(m, _top(q, 0.03 + 0.1 * q, 0.01)))
                pfold = 1.0 - q
                for v in callers:
                    pfold *= 0.8
                for v in behind:
                    pfold *= 0.93
                cont = 1.0 - pfold
                if jam:
                    ev = pfold * pot + cont * (eqc * (pot + inv + addv) - inv)
                else:
                    pr = cont * p4 / q if q > 1e-6 else 0.0        # he re-raises, usually all in
                    r3 = min(1.0, rzn + 0.08)
                    eqt = eqv(_apply(m, _top(max(0.02, p4), 0.03 + 0.1 * p4, 0.01)))
                    ev_sh = eqt * (dead + 2 * sv) - (sv - bets[me])  # we call it off ...
                    if ev_sh < -inv:
                        ev_sh = -inv                                 # ... or give up the raise
                    if V11_JAM_FIX and hp > (0.05 if o.g < 0.9 else max(0.14, min(0.35, 1.5 * max(0.02, p4) * frac))):
                        ev_sh = -inv                                 # v11: the shove guard will fold this hand
                    if nr == 1 and o.g >= 0.6 and kn >= 5 and p4 >= 0.45 and eqt < 0.52:
                        continue                # he re-raises almost always: do not 3-bet a hand we would then fold
                    ev = pfold * pot + (cont - pr) * (r3 * eqc * (pot + inv + addv) - inv) + pr * ev_sh
                risk = inv / s0
                if risk > 0.1:
                    ev -= VPEN * risk * risk * (pot + inv + addv) * cont
                if nr >= 2 and not jam and not b4 and hp > 0.035 and (o.g < 0.6 or frac < 0.12):
                    continue                # 4-bet a tight or unknown 3-bettor with premiums only
                sticky = o.g >= 0.6 and o.ds_n >= 4 and o.ds_c >= 0.8 * o.ds_n
                if (jam or nr >= 2) and not b4 and eqc < (0.52 if sticky else 0.55) and hp > 0.03:
                    continue                # big preflop pots need a clear edge when called, not a coin flip
                if eqc < 0.45:
                    # a bluff: only versus a raiser we have SEEN fold to re-raises, with a blocker hand
                    seen = o.g >= 0.5 and kn >= 5 and kf >= 0.62 * kn
                    if b4:
                        umax_ = 0.5
                        wide4 = False
                        if V13_4BET_WIDE and me in self.prs and kn >= 5 and kf >= 0.75 * kn and o.tbus(0.11) >= 0.15:
                            umax_ = 0.75
                            wide4 = (i == j or i == 0 or j == 0 or (i < j and (i <= 2 or j - i <= 3))
                                     or (i > j and j <= 2 and i <= 4))
                        if not ((blocker or i == 0 or j == 0 or i == j or wide4) and u <= umax_):
                            continue        # v11: 4-bet bluff only vs a measured 4-bet folder, ace/pair/blocker hands
                    elif V12_LIGHT3 and not jam and nr == 1:
                        seen2 = o.g >= 0.5 and kn >= 4 and kf >= 0.55 * kn
                        ok3_ = seen2 and (blocker or i == 0 or j == 0 or i == j) and u <= 0.45
                        if (not ok3_ and V18_PF_P > 0 and not callers and (blocker or i == 0 or i == j)
                                and (kn < 4 or kf >= 0.45 * kn) and self._u(600 + nr) <= V18_PF_P):
                            ok3_ = True     # v18: occasional light 3-bet vs an opener not measured to defend
                        if not ok3_:
                            continue        # v12: light 3-bet vs a measured 3-bet folder (55%+)
                    elif jam or nr >= 2 or not (seen and blocker and u <= 0.35):
                        continue
                if ev > best_ev + 0.5 * bb + (1.0 * bb if jam else 0.0):
                    best_ev = ev
                    best = {"action": "raise", "amount": int(x)}
        return best

    def _jam_ev(self, live, acted, row, pot, inv, bets, stacks, s0):
        """EV of an open/iso jam from each opponent's (gated) call-a-shove frequency and range."""
        opp = self.opp
        pfw = self.pfw
        rs = []
        for v in live:
            if stacks[v] <= 0:
                continue
            o = opp[v]
            m = pfw[v]
            pc = o.callshove()
            if v in acted:
                pc = min(1.0, pc * 1.5)
            if pc < 0.02:
                continue
            mc = _apply(m, _top(pc, 0.02 + 0.12 * pc, 0.005))
            t = sum(mc)
            e = sum(map(mul, mc, row)) / t if t > 1e-9 else 0.3
            rs.append((pc, e, min(stacks[v], s0 - bets[v])))
        rs.sort(reverse=True)
        rs = rs[:3]
        k = len(rs)
        ev = 0.0
        pany = 0.0
        for mask in range(1 << k):
            p = 1.0
            e = 1.0
            adds = 0
            for i in range(k):
                q, ei, ad = rs[i]
                if (mask >> i) & 1:
                    p *= q
                    e *= ei
                    adds += ad
                else:
                    p *= 1.0 - q
            if mask == 0:
                ev += p * pot
            else:
                ev += p * (e * (pot + inv + adds) - inv)
                pany += p
        risk = inv / s0
        return ev - VPEN * risk * risk * (pot + 2 * inv) * pany

    # ----------------------------------------------------------------- layer 2: learning
    def _learn(self, sm):
        """Replay the finished hand and update every opponent's frequencies (incl. showdowns)."""
        hist = sm["history"]
        opp = self.opp
        if opp is None:
            return
        shv = 0.4 * self.S0
        shc = 0.33 * self.S0
        cur = None
        si = 0
        lvl = 0
        nr = 0
        pot = 0
        opener = -1                         # v11
        rv_first = -1                       # v11: first bettor on the river
        me_ = self.me
        rb = {}
        seen = set()
        shoved = set()
        pfr = set()
        agg = set()
        for e in hist:
            a = e["action"]
            seat = e["seat"]
            st = e["street"]
            if st != cur:
                cur = st
                si = STREET_IDX[st]
                rb = {}
                lvl = 0
                agg = set()
            amt = e["amount"]
            if a == "small_blind" or a == "big_blind":
                rb[seat] = amt
                pot += amt
                if amt > lvl:
                    lvl = amt
                continue
            o = opp[seat]
            mine = rb.get(seat, 0)
            tc = lvl - mine
            o.n += 1
            if si == 0:
                if seat not in seen:
                    seen.add(seat)
                    o.fd_n += 1
                if tc >= shc:
                    if seat in pfr:
                        o.ds_n += 1
                        if a != "fold":
                            o.ds_c += 1
                    else:
                        o.fs_n += 1
                        if a != "fold":
                            o.fs_c += 1
                elif nr == 0:
                    o.uo_n += 1
                    if a == "raise":
                        o.uo_r += 1
                    elif a == "call":
                        o.uo_l += 1
                elif nr == 1:
                    o.fr_n += 1
                    if a == "raise":
                        o.fr_r += 1
                    elif a == "call":
                        o.fr_c += 1
                    if opener == me_ and seat != me_:
                        o.tu_n += 1                 # v11: he faced OUR open
                        if a == "raise":
                            o.tu_r += 1
                elif seat in pfr:
                    if nr == 2:
                        o.d3_n += 1
                        if a == "raise":
                            o.d3_r += 1
                        elif a == "call":
                            o.d3_c += 1
                    else:
                        o.d4_n += 1
                        if a == "raise":
                            o.d4_r += 1
                        elif a == "call":
                            o.d4_c += 1
                else:
                    o.f3_n += 1                     # cold: says nothing about how he defends his own raise
                    if a == "raise":
                        o.f3_r += 1
                    elif a == "call":
                        o.f3_c += 1
                if a == "raise":
                    pfr.add(seat)
                    if amt >= shv and seat not in shoved:
                        shoved.add(seat)
                        o.fd_sh += 1
            elif tc <= 0:
                o.cb_n[si] += 1
                if a == "raise":
                    o.cb_b[si] += 1
                    if si == 3 and rv_first < 0:
                        rv_first = seat             # v11
                    o.bs_n += 1
                    o.bs_sum += min(3.0, amt / pot) if pot > 0 else 0.6
            elif seat in agg:
                o.br_n += 1                         # he bet and got raised
                if a == "fold":
                    o.br_f += 1
            else:
                b = _bucket(tc, pot)
                o.fb_n[b] += 1
                if a == "fold":
                    o.fb_f[b] += 1
                elif a == "raise":
                    o.fb_r[b] += 1
            if a == "call":
                rb[seat] = mine + amt
                pot += amt
            elif a == "raise":
                pot += amt - mine
                rb[seat] = amt
                lvl = amt
                if si == 0:
                    if nr == 0:
                        opener = seat               # v11
                    nr += 1
                else:
                    agg.add(seat)
        shown = sm.get("shown") or {}
        bd_ = sm.get("board") or []
        for k, cards in shown.items():
            seat = int(k)
            if (V11_HONESTY or V13_WEAKPAIR) and seat == rv_first and seat != me_ and len(bd_) == 5:
                try:
                    hc_ = [CARD[cards[0]], CARD[cards[1]]]
                    v_ = ev7(hc_ + [CARD[c] for c in bd_])
                    cat_ = v_ >> 20
                    air_ = cat_ == 0 or (cat_ == 1 and ((v_ >> 16) & 15) not in (hc_[0] >> 2, hc_[1] >> 2))
                    o_ = opp[seat]
                    o_.ra_n += 1
                    if air_:
                        o_.ra_air += 1
                except Exception:
                    pass
            if seat in pfr:
                a, b = CARD[cards[0]], CARD[cards[1]]
                pct = PCT[CLS[KID[a * 52 + b]]]
                o = opp[seat]
                o.sd_r_n += 1
                o.sd_r_sum += pct
                if seat in shoved:
                    o.sd_s_n += 1
                    o.sd_s_sum += pct
        for o in opp:
            g = (o.n - 20) / 40.0
            o.g = 0.0 if g < 0.0 else (1.0 if g > 1.0 else g)


gc.collect()
gc.freeze()
gc.disable()
