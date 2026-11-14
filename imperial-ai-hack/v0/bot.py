"""v0 fast-lane pokerbot: table-driven tight-aggressive preflop, Monte Carlo
equity vs random hands postflop with simple thresholds. Standard library only."""
import gc
import random
import time
import base64
import zlib

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
# Equity of each class vs a uniformly random hand (combo-weighted, card removal ignored).
PF_VS_RANDOM = [sum(PF_EQ[a][b] * PF_COMBOS[b] for b in range(169)) / 1326.0 for a in range(169)]


def pf_class_index(c1, c2):
    """Class index from two card strings like "As", "Kd"."""
    i, j = _R.index(c1[0]), _R.index(c2[0])
    if i == j:
        return i * 13 + j
    hi, lo = (i, j) if i < j else (j, i)
    return hi * 13 + lo if c1[1] == c2[1] else lo * 13 + hi

_perf = time.perf_counter
_rnd = random.random

# ----------------------------------------------------------------------------
# Preflop tables
# ----------------------------------------------------------------------------
PF_PCT = [1.0] * 169          # PF_PCT[k] = k is inside the top PF_PCT[k] share of hands
_cum = 0
for _k in sorted(range(169), key=lambda q: -PF_VS_RANDOM[q]):
    _cum += PF_COMBOS[_k]
    PF_PCT[_k] = _cum / 1326.0


def _set(names):
    return frozenset(PF_INDEX[x] for x in names.split())


S_JAM = _set("AA KK")
S_3BET = _set("AA KK QQ AKs AKo")
S_4B_CONT = _set("AA KK QQ AKs")
S_CALL = _set("JJ TT 99 88 77 66 55 44 33 22 AQs AJs ATs KQs KJs KTs QJs QTs JTs AQo")
S_CALL_MID = _set("JJ TT AQs")
S_BIG_HU = _set("AA KK QQ JJ TT AKs AKo")
S_BIG_HU_3B = _set("AA KK QQ JJ AKs AKo")
S_BIG_MULTI = _set("AA KK QQ")
S_SPEC = frozenset(k for k in range(169) if (k // 13) <= (k % 13) and PF_PCT[k] <= 0.60)
IDX_JJ = PF_INDEX["JJ"]

# ----------------------------------------------------------------------------
# Hand evaluator tables (card int = rank * 4 + suit, rank 0..12 for 2..A)
# ----------------------------------------------------------------------------
_RANKS = "23456789TJQKA"
_SUITS = "cdhs"
_CI = {}
for _r in range(13):
    for _s in range(4):
        _CI[_RANKS[_r] + _SUITS[_s]] = _r * 4 + _s

RK = [5 ** (c >> 2) for c in range(52)]
# bits 0..51: one 13-bit rank mask per suit; bits 52..63: a 3-bit card counter per suit
SK = [(1 << (52 + 3 * (c & 3))) + (1 << (13 * (c & 3) + (c >> 2))) for c in range(52)]

STR = [-1] * 8192            # highest rank of a straight in a 13-bit rank mask, or -1
FL = [0] * 8192              # strength of the best flush / straight flush in a suit mask
FS = [-1] * 4096             # suit counters -> bit shift of the flush suit, or -1
NF = {}                      # rank multiset key (5, 6 or 7 cards) -> non-flush strength


def _build_tables():
    for m in range(8192):
        mm = (m << 1) | ((m >> 12) & 1)
        for top in range(13, 3, -1):
            if (mm >> (top - 4)) & 31 == 31:
                STR[m] = top - 1
                break
    for m in range(8192):
        if bin(m).count("1") < 5:
            continue
        sh = STR[m]
        if sh >= 0:
            FL[m] = (8 << 20) | (sh << 16)
        else:
            v = 5 << 20
            shift = 16
            for r in range(12, -1, -1):
                if (m >> r) & 1:
                    v |= r << shift
                    shift -= 4
                    if shift < 0:
                        break
            FL[m] = v
    for idx in range(4096):
        for s in range(4):
            if ((idx >> (3 * s)) & 7) >= 5:
                FS[idx] = 13 * s
                break

    nf = NF
    strt = STR
    p5 = [5 ** r for r in range(13)]

    def strength(q, tr, pr, sg, mask):
        if q >= 0:
            k = -1
            if tr:
                k = tr[0]
            if pr and pr[0] > k:
                k = pr[0]
            if sg and sg[0] > k:
                k = sg[0]
            return (7 << 20) | (q << 16) | (k << 12)
        if tr:
            if len(tr) > 1:
                return (6 << 20) | (tr[0] << 16) | (tr[1] << 12)
            if pr:
                return (6 << 20) | (tr[0] << 16) | (pr[0] << 12)
        sh = strt[mask]
        if sh >= 0:
            return (4 << 20) | (sh << 16)
        if tr:
            return (3 << 20) | (tr[0] << 16) | (sg[0] << 12) | (sg[1] << 8)
        if len(pr) >= 2:
            k = pr[2] if len(pr) > 2 else -1
            if sg and sg[0] > k:
                k = sg[0]
            return (2 << 20) | (pr[0] << 16) | (pr[1] << 12) | (k << 8)
        if pr:
            return (1 << 20) | (pr[0] << 16) | (sg[0] << 12) | (sg[1] << 8) | (sg[2] << 4)
        return (sg[0] << 16) | (sg[1] << 12) | (sg[2] << 8) | (sg[3] << 4) | sg[4]

    def rec(rmax, n, key, mask, q, tr, pr, sg):
        for r in range(rmax, -1, -1):
            pk = p5[r]
            m2 = mask | (1 << r)
            for c in (1, 2, 3, 4):
                n2 = n + c
                if n2 > 7:
                    break
                k2 = key + pk * c
                q2 = q
                tr2 = tr
                pr2 = pr
                sg2 = sg
                if c == 1:
                    sg2 = sg + (r,)
                elif c == 2:
                    pr2 = pr + (r,)
                elif c == 3:
                    tr2 = tr + (r,)
                else:
                    q2 = r
                if n2 >= 5:
                    nf[k2] = strength(q2, tr2, pr2, sg2, m2)
                if n2 < 7 and r > 0:
                    rec(r - 1, n2, k2, m2, q2, tr2, pr2, sg2)

    rec(12, 0, 0, 0, -1, (), (), ())


_build_tables()


def evaluate_ints(cards):
    """Strength of the best 5-card hand from 5-7 card ints. Higher wins."""
    r = 0
    s = 0
    for c in cards:
        r += RK[c]
        s += SK[c]
    f = FS[s >> 52]
    if f >= 0:
        return FL[(s >> f) & 8191]
    return NF[r]


def _equity(hole, board, n_opp, deadline, maxit):
    """Probability of winning (ties shared) vs n_opp random hands."""
    ci = _CI
    h0 = ci[hole[0]]
    h1 = ci[hole[1]]
    bl = [ci[c] for c in board]
    deck = [c for c in range(52) if c != h0 and c != h1 and c not in bl]
    rk = RK
    sk = SK
    nf = NF
    fl = FL
    fs = FS
    brk = 0
    bsk = 0
    for c in bl:
        brk += rk[c]
        bsk += sk[c]
    hrk = rk[h0] + rk[h1]
    hsk = sk[h0] + sk[h1]
    nb = 5 - len(bl)
    n = len(deck)
    if nb < 0:
        return 0.5
    if nb == 0 and n_opp == 1:
        # river heads-up: exact enumeration of every villain hand
        s = bsk + hsk
        f = fs[s >> 52]
        mine = fl[(s >> f) & 8191] if f >= 0 else nf[brk + hrk]
        drk = [rk[c] for c in deck]
        dsk = [sk[c] for c in deck]
        score = 0
        for i in range(n - 1):
            r1 = brk + drk[i]
            s1 = bsk + dsk[i]
            for j in range(i + 1, n):
                s = s1 + dsk[j]
                f = fs[s >> 52]
                v = fl[(s >> f) & 8191] if f >= 0 else nf[r1 + drk[j]]
                if v < mine:
                    score += 2
                elif v == mine:
                    score += 1
        return score / float(n * (n - 1))
    k = nb + 2 * n_opp
    if k > n:
        return 0.5
    rng_k = range(k)
    rng_b = range(nb)
    rng_o = range(nb, k, 2)
    wins = 0.0
    it = 0
    rnd = _rnd
    perf = _perf
    while it < maxit:
        if (it & 31) == 31 and perf() > deadline:
            break
        it += 1
        for j in rng_k:
            i = j + int(rnd() * (n - j))
            c = deck[i]
            deck[i] = deck[j]
            deck[j] = c
        r = brk
        s0 = bsk
        for j in rng_b:
            c = deck[j]
            r += rk[c]
            s0 += sk[c]
        s = s0 + hsk
        f = fs[s >> 52]
        mine = fl[(s >> f) & 8191] if f >= 0 else nf[r + hrk]
        ties = 0
        for j in rng_o:
            c1 = deck[j]
            c2 = deck[j + 1]
            s = s0 + sk[c1] + sk[c2]
            f = fs[s >> 52]
            v = fl[(s >> f) & 8191] if f >= 0 else nf[r + rk[c1] + rk[c2]]
            if v > mine:
                break
            if v == mine:
                ties += 1
        else:
            wins += 1.0 if ties == 0 else 1.0 / (ties + 1)
    if it == 0:
        return 0.5
    return wins / it


# ----------------------------------------------------------------------------
# Action helpers (always legal, raises clamped)
# ----------------------------------------------------------------------------
_CHECK = {"action": "check"}
_CALL = {"action": "call"}
_FOLD = {"action": "fold"}


def _passive(st):
    """Check if we can, otherwise fold."""
    legal = st.get("legal_actions") or ()
    if "check" in legal:
        return {"action": "check"}
    return {"action": "fold"}


def _call(st):
    legal = st.get("legal_actions") or ()
    if "call" in legal and (st.get("to_call") or 0) > 0:
        return {"action": "call"}
    if "check" in legal:
        return {"action": "check"}
    if "call" in legal:
        return {"action": "call"}
    return {"action": "fold"}


def _raise(st, amount):
    legal = st.get("legal_actions") or ()
    if "raise" in legal:
        lo = st.get("min_raise_to")
        hi = st.get("max_raise_to")
        if lo is not None and hi is not None:
            a = int(amount)
            if a < lo:
                a = int(lo)
            if a > hi:
                a = int(hi)
            return {"action": "raise", "amount": a}
    return _call(st)


def _dry(board):
    """Flop without a flush or straight texture."""
    if len(board) != 3:
        return False
    if board[0][1] == board[1][1] == board[2][1]:
        return False
    rs = sorted(set(_RANKS.index(c[0]) for c in board))
    if len(rs) == 3 and rs[2] - rs[0] <= 4:
        return False
    return True


class Agent:
    def __init__(self):
        self.spent = 0.0
        self.start = 2000

    def on_table_start(self, info):
        try:
            v = info.get("starting_stack")
            if v:
                self.start = int(v)
        except Exception:
            pass

    def on_hand_end(self, summary):
        return None

    def act(self, state):
        t0 = _perf()
        try:
            a = self._decide(state, t0)
            if not isinstance(a, dict) or a.get("action") not in ("fold", "check", "call", "raise"):
                a = _passive(state)
        except Exception:
            try:
                a = _passive(state)
            except Exception:
                a = {"action": "fold"}
        self.spent += _perf() - t0
        return a

    # ------------------------------------------------------------------
    def _decide(self, st, t0):
        seat = st["seat"]
        stacks = st["stacks"]
        folded = st["folded"]
        n = len(stacks)
        bb = st.get("big_blind") or 20
        to_call = st.get("to_call") or 0
        n_opp = 0
        for i in range(n):
            if i != seat and not folded[i]:
                n_opp += 1
        if n_opp < 1:
            n_opp = 1
        if st.get("street") == "preflop" or not st.get("board"):
            return self._preflop(st, seat, n, bb, to_call)
        return self._postflop(st, t0, seat, n_opp, bb, to_call)

    # ------------------------------------------------------------------
    def _preflop(self, st, seat, n, bb, to_call):
        hole = st["hole_cards"]
        cls = pf_class_index(hole[0], hole[1])
        pct = PF_PCT[cls]
        button = st["button"]
        bets = st["bets"]
        stacks = st["stacks"]
        pot = st["pot"]
        my_stack = stacks[seat]
        my_bet = bets[seat]
        max_bet = max(bets)
        n_raises = 0
        limpers = 0
        callers = 0
        raiser = -1
        for h in st.get("history") or ():
            a = h.get("action")
            if a == "raise":
                n_raises += 1
                raiser = h.get("seat")
                callers = 0
            elif a == "call":
                if n_raises == 0:
                    limpers += 1
                elif h.get("seat") != seat:
                    callers += 1
        off = (seat - button) % n

        # ---- nobody has raised yet ----
        if n_raises == 0:
            if to_call <= 0:
                if pct <= 0.12:
                    return _raise(st, (4 + limpers) * bb)
                return _passive(st)
            if off == 0:
                thr = 0.42
            elif off == 1:
                thr = 0.35
            elif off == 2:
                thr = 0.12
            else:
                d = n - off
                thr = 0.27 if d == 1 else (0.20 if d == 2 else (0.14 if d == 3 else 0.10))
            if limpers and thr > 0.22:
                thr = 0.22
            if pct <= thr:
                size = (3.0 if off == 1 else 2.5) * bb + limpers * bb
                return _raise(st, size)
            if limpers and to_call <= bb and cls in S_SPEC:
                return _call(st)
            if off == 1 and limpers and pct <= 0.55:
                return _call(st)
            return _passive(st)

        cost = to_call
        raiser_allin = 0 <= raiser < n and stacks[raiser] == 0
        big = cost > 25 * bb or raiser_allin or cost >= my_stack
        hu = callers == 0

        # ---- facing exactly one raise ----
        if n_raises == 1:
            if big:
                if cls in S_JAM:
                    return _raise(st, st.get("max_raise_to") or 0)
                if cls in (S_BIG_HU if hu else S_BIG_MULTI):
                    return _call(st)
                return _passive(st)
            if cls in S_3BET:
                in_pos = ((seat - button - 1) % n) > ((raiser - button - 1) % n)
                amt = max_bet * (3 if in_pos else 4) + callers * max_bet
                return _raise(st, amt)
            if off == 2:
                if max_bet <= 2.5 * bb and pct <= 0.55:
                    return _call(st)
                if max_bet <= 3.5 * bb and pct <= 0.40:
                    return _call(st)
            if cost <= 5 * bb and cls in S_CALL:
                return _call(st)
            if cost <= 10 * bb and cls in S_CALL_MID:
                return _call(st)
            if cls == IDX_JJ and hu:
                return _call(st)
            if my_bet >= bb and cost <= 2 * bb and cost <= 0.2 * (pot + cost) and (cls in S_SPEC or pct <= 0.45):
                return _call(st)
            return _passive(st)

        # ---- facing a 3-bet or more ----
        if cls in S_JAM:
            return _raise(st, st.get("max_raise_to") or 0)
        if big:
            if cls in (S_BIG_HU_3B if hu else S_BIG_MULTI):
                return _call(st)
            return _passive(st)
        if cls in S_4B_CONT:
            return _call(st)
        po = cost / float(pot + cost)
        if po <= 0.30 and cost <= 6 * bb and (cls in S_CALL or cls in S_3BET):
            return _call(st)
        if po <= 0.20 and cost <= 3 * bb and my_bet > bb:
            return _call(st)
        return _passive(st)

    # ------------------------------------------------------------------
    def _postflop(self, st, t0, seat, n_opp, bb, to_call):
        board = st["board"]
        hole = st["hole_cards"]
        street = st.get("street")
        pot = st["pot"]
        bets = st["bets"]
        my_stack = st["stacks"][seat]
        my_bet = bets[seat]
        max_bet = max(bets)
        start = self.start
        rts = st.get("raises_this_street") or 0
        can_raise = "raise" in st["legal_actions"]

        sp = self.spent
        if sp < 4.5:
            budget = 0.0017
            maxit = 1200
        elif sp < 6.5:
            budget = 0.0006
            maxit = 400
        else:
            budget = 0.00015
            maxit = 96
        no = n_opp if n_opp < 5 else 5
        eq = _equity(hole, board, no, t0 + budget, maxit)
        e1 = eq ** (1.0 / no) if no > 1 else eq      # heads-up equivalent
        extra = no - 1 if no < 4 else 3

        if to_call <= 0:
            if can_raise:
                vt = (0.62 if street == "flop" else (0.65 if street == "turn" else 0.70)) + 0.04 * extra
                if e1 >= vt:
                    frac = 0.8 if e1 >= 0.88 else 0.66
                    return _raise(st, my_bet + frac * pot)
                if street == "flop" and n_opp == 1 and rts == 0 and _dry(board) and _rnd() < 0.5:
                    last = -1
                    for h in st.get("history") or ():
                        if h.get("street") != "preflop":
                            break
                        if h.get("action") == "raise":
                            last = h.get("seat")
                    if last == seat:
                        return _raise(st, my_bet + 0.33 * pot)
            return _passive(st)

        # ---- facing a bet ----
        po = to_call / float(pot + to_call)
        prev = pot - to_call
        if prev < 1:
            prev = 1
        bf = to_call / float(prev)
        if bf > 1.5:
            bf = 1.5
        need = po + 0.10 + 0.15 * bf + 0.03 * extra + 0.20 * to_call / float(start)
        if street == "river":
            need += 0.04
        if need > 0.84:
            need = 0.84
        commit = (start - my_stack + to_call) / float(start)

        if can_raise and e1 >= 0.90 + 0.02 * extra and (rts < 2 or e1 >= 0.96):
            hi = st.get("max_raise_to") or 0
            target = max_bet + 0.75 * (pot + to_call)
            if target >= 0.6 * hi:
                if e1 >= 0.94:
                    return _raise(st, hi)
                return _call(st)
            return _raise(st, target)
        if commit > 0.40 and to_call > 0.08 * start and po > 0.15 and e1 < 0.80 + 0.03 * extra:
            return _passive(st)
        if eq >= need:
            return _call(st)
        return _passive(st)


try:
    gc.collect()
    gc.freeze()
    gc.disable()
except Exception:
    pass
