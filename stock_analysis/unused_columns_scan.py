import re


# Paste of the formula lines (one per row) from the sheet portion starting at column D.
# Numeric results from the GoogleFinance call are intentionally not included because they
# don't start with '='.
FORMULA_TEXT = r"""
=WORKDAY.INTL(D1662, 1, 1, Holidays!B:B)
=QUERY(GOOGLEFINANCE(C$1, "all", D1663, D1663), "SELECT Col2, Col3, Col4, Col5, Col6 OFFSET 1", 0)
=IF(ROW()<=9,"",INDEX($F:$F,ROW())=MAX(INDEX($F:$F,ROW()-4):INDEX($F:$F,ROW()+4)))
=IF(ROW()<=9,"",(MIN(INDEX($G:$G,ROW()+1):INDEX($G:$G,ROW()+7))/INDEX($F:$F,ROW())-1)<=-0.06)
=IF(ROW()<=9,"",COUNTIFS(INDEX($N:$N,MAX(2,ROW()-4)):INDEX($N:$N,ROW()-1),"Pivot High",INDEX($T:$T,MAX(2,ROW()-4)):INDEX($T:$T,ROW()-1),">="&INDEX($F:$F,ROW())*(1-0.01),INDEX($T:$T,MAX(2,ROW()-4)):INDEX($T:$T,ROW()-1),"<="&INDEX($F:$F,ROW())*(1+0.01))=0)
=IF(ROW()<=9,"",NOT(AND(INDEX($G:$G,ROW())=MIN(INDEX($G:$G,ROW()-4):INDEX($G:$G,ROW()+4)),(MAX(INDEX($F:$F,ROW()+1):INDEX($F:$F,ROW()+7))/INDEX($G:$G,ROW())-1)>=0.06,COUNTIFS(INDEX($S:$S,MAX(2,ROW()-4)):INDEX($S:$S,ROW()-1),"Pivot Low",INDEX($U:$U,MAX(2,ROW()-4)):INDEX($U:$U,ROW()-1),">="&INDEX($G:$G,ROW())*(1-0.01),INDEX($U:$U,MAX(2,ROW()-4)):INDEX($U:$U,ROW()-1),"<="&INDEX($G:$G,ROW())*(1+0.01))=0)))
=IF(ROW()<=9,"",IF(AND(INDEX($J:$J,ROW()),INDEX($K:$K,ROW()),INDEX($L:$L,ROW()),INDEX($M:$M,ROW())),"Pivot High",""))
=IF(ROW()<=9,"",INDEX($G:$G,ROW())=MIN(INDEX($G:$G,ROW()-4):INDEX($G:$G,ROW()+4)))
=IF(ROW()<=9,"",(MAX(INDEX($F:$F,ROW()+1):INDEX($F:$F,ROW()+7))/INDEX($G:$G,ROW())-1)>=0.06)
=IF(ROW()<=9,"",COUNTIFS(INDEX($S:$S,MAX(2,ROW()-4)):INDEX($S:$S,ROW()-1),"Pivot Low",INDEX($U:$U,MAX(2,ROW()-4)):INDEX($U:$U,ROW()-1),">="&INDEX($G:$G,ROW())*(1-0.01),INDEX($U:$U,MAX(2,ROW()-4)):INDEX($U:$U,ROW()-1),"<="&INDEX($G:$G,ROW())*(1+0.01))=0)
=IF(ROW()<=9,"",NOT(AND(INDEX($F:$F,ROW())=MAX(INDEX($F:$F,ROW()-4):INDEX($F:$F,ROW()+4)),(MIN(INDEX($G:$G,ROW()+1):INDEX($G:$G,ROW()+7))/INDEX($F:$F,ROW())-1)<=-0.06,COUNTIFS(INDEX($N:$N,MAX(2,ROW()-4)):INDEX($N:$N,ROW()-1),"Pivot High",INDEX($T:$T,MAX(2,ROW()-4)):INDEX($T:$T,ROW()-1),">="&INDEX($F:$F,ROW())*(1-0.01),INDEX($T:$T,MAX(2,ROW()-4)):INDEX($T:$T,ROW()-1),"<="&INDEX($F:$F,ROW())*(1+0.01))=0)))
=IF(ROW()<=9,"",IF(AND(INDEX($O:$O,ROW()),INDEX($P:$P,ROW()),INDEX($Q:$Q,ROW()),INDEX($R:$R,ROW())),"Pivot Low",""))
=IF(N1663="Pivot High",F1663,"")
=IF(S1663="Pivot Low",G1663,"")
=IF(T1663<>"",T1663,IF(ROW()=2,"",V1662))
=IF(U1663<>"",U1663,IF(ROW()=2,"",W1662))
=IF(AND(T1663<>"",T1663>V1662),"HH","")
=IF(AND(T1663<>"",T1663<V1662),"LH","")
=IF(AND(U1663<>"",U1663>W1662),"HL","")
=IF(AND(U1663<>"",U1663<W1662),"LL","")
=IF(N1663<>"Pivot High","",IF(INDEX($AA:$AA,ROW()+MATCH("Pivot Low",INDEX($S:$S,ROW()+1):$S$100594,0)))="LL","Major High",""))
=IF(S1663<>"Pivot Low","",IF(INDEX($X:$X,ROW()+MATCH("Pivot High",INDEX($N:$N,ROW()+1):$N$100594,0)))="HH","Major Low",""))
=IFERROR(IF(ROW()<=1+$C$17,"",IF(N1663="Pivot High",(F1663/MIN(INDEX($G:$G,ROW()-$C$17):INDEX($G:$G,ROW()-1))-1)>=$C$18,"")),"")
=IFERROR(IF(ROW()<=1+$C$17,"",IF(S1663="Pivot Low",(1-G1663/MAX(INDEX($F:$F,ROW()-$C$17):INDEX($F:$F,ROW()-1)))>=$C$18,"")),"")
=IFERROR(IF(ROW()<=1+$C$14,"",IF(AND(N1663="Pivot High",AD1663=TRUE,(1-MIN(INDEX($G:$G,ROW()+1):INDEX($G:$G,ROW()+$C$14))/F1663)>=$C$15),F1663,IF(AND(S1663="Pivot Low",AE1663=TRUE,(MAX(INDEX($F:$F,ROW()+1):INDEX($F:$F,ROW()+$C$14))/G1663-1)>=$C$15),G1663,""))),"")
=IF(AF1663="","",AF1663*(1-$C$5))
=IF(AF1663="","",AF1663*(1+$C$5))
=IF($DE1663="","",AND(ROW()>$DG1663,$G1663<=$DF1663,$F1663>=$DE1663,$H1663>$DF1663))
=IF($DE1663="","",AND(ROW()>$DG1663,$G1663<=$DF1663,$F1663>=$DE1663,$H1663<$DE1663))
=IF(OR($DE1663="",$DF1663=""),"",AND(ROW()>$DG1663,$H1662>$DF1663,$G1663<=$DF1663,$F1663>=$DE1663))
=IF(OR($DE1663="",$DF1663=""),"",AND(ROW()>$DG1663,$H1662<$DE1663,$G1663<=$DF1663,$F1663>=$DE1663))
=IF($DF1663="","",COUNTIFS(INDEX($AK:$AK,MAX(2,ROW()-$C$10)):INDEX($AK:$AK,ROW()),TRUE,INDEX($DF:$DF,MAX(2,ROW()-$C$10)):INDEX($DF:$DF,ROW()),$DF1663)>=2)
=IF($DH1663="","",COUNTIFS(INDEX($AL:$AL,MAX(2,ROW()-$C$10)):INDEX($AL:$AL,ROW()),TRUE,INDEX($DH:$DH,MAX(2,ROW()-$C$10)):INDEX($DH:$DH,ROW()),$DH1663)>0)
=IF(OR($DE1663="",$DF1663=""),"",AND($AM1663=TRUE,$AN1663=TRUE))
=IF(OR($DE1663="",$DF1663=""),"",MAX(INDEX($H:$H,MAX(2,ROW()-$C$16+1)):$H1663)>$DF1663)
=IF(OR($DE1663="",$DF1663=""),"",OR($AM1663=TRUE,AND($AN1663=TRUE,$AP1663=TRUE)))
=IF($DE1663="","",COUNTIFS(INDEX($CD:$CD,MAX(2,ROW()-$C$10)):INDEX($CD:$CD,ROW()),">="&$DE1663,INDEX($CD:$CD,MAX(2,ROW()-$C$10)):INDEX($CD:$CD,ROW()),"<="&$DF1663))
=IF(AR1663="","",AR1663>=$C$6)
=IF(CD1663="","",COUNTIFS(INDEX($CD:$CD,MAX(2,ROW()-C$11)):INDEX($CD:$CD,ROW()),">="&CE1663,INDEX($CD:$CD,MAX(2,ROW()-C$11)):INDEX($CD:$CD,ROW()),"<="&CF1663))
=IF(AT1663="","",AT1663>=2)
=IF(AND(AS1663=TRUE,AU1663=TRUE),TRUE,FALSE)
=IF(N($AR1663)=0,"",AND(N($AR1663)>=$C$6,OR(N($AR1662)<$C$6,$DH1663<>$DH1662)))
=IF(ROW()=2,FALSE,IF(OR($AY1662="",OR($H1663>$AY1662,$H1663<$AZ1662)),FALSE,AND($BA1663>=3,$BB1663>=3,$H1663<=$AY1663,$H1663>=$AZ1663)))
=IF(ROW()=2,$V1663,IF(OR($AY1662="",OR($H1663>$AY1662,$H1663<$AZ1662)),$V1663,$AY1662))
=IF(ROW()=2,$W1663,IF(OR($AZ1662="",OR($H1663>$AY1662,$H1663<$AZ1662)),$W1663,$AZ1662))
=IF(ROW()=2,IF(AND($O1663<>"Pivot High",$T1663<=$AY1663),1,0),IF(OR($AY1662="",$H1663>$AY1662,$H1663<$AZ1662),IF(AND($O1663<>"Pivot High",$T1663<=$AY1663),1,0),$BA1662+IF(AND($O1663<>"Pivot High",$T1663<=$AY1663),1,0)))
=IF(ROW()=2,IF(AND($S1663<>"Pivot Low",$U1663>=$AZ1663),1,0),IF(OR($AZ1662="",OR($H1663>$AY1662,$H1663<$AZ1662)),IF(AND($S1663<>"Pivot Low",$U1663>=$AZ1663),1,0),$BB1662+IF(AND($S1663<>"Pivot Low",$U1663>=$AZ1663),1,0)))
=IF(OR($AW1663<>TRUE,ROW()<=105),"",(MAX(INDEX($F:$F,ROW()-104):$F1663)/MIN(INDEX($G:$G,ROW()-104):$G1663)-1)>$C$7)
=IF(ROW()=2,"",IF($BL1662=TRUE,$BD1662,IF($BI1663=TRUE,$E1664*(1+$C$3),"")))
=AND(H1663>E1663,H1663>=G1663+((F1663-G1663)/2))
=IF(OR($DE1663="",$DF1663=""),"",AND(ROW()>$DG1663,$H1662<$DE1663,$G1663<=$DF1663,$F1663>=$DE1663))
=AND($D1663>=DATE(2019,1,1),$BW1663=TRUE,OR($BC1663=TRUE,$BC1662=TRUE),$BE1663=TRUE,$BG1663=TRUE,OR($AK1663=TRUE,$AK1662=TRUE),OR($AQ1663=TRUE,$AQ1662=TRUE))
=IF(ROW()=2,"",IF($BL1662=TRUE,$BJ1662,IF($BI1663=TRUE,$G1663*(1-$C$4),"")))
=IF(ROW()=2,"",IF($BL1662<>TRUE,"",$F1663>=$BD1663))
=IF(ROW()=2,"",IF($BL1662=TRUE,IF($BN1663<>"","",TRUE),$BI1663=TRUE))
=IF(BL1663<>TRUE,"",(BD1663-BP1663)/(BP1663-BJ1663))
=IF($BL1662<>TRUE,"",IF(AND($E1663<=$BJ1663,$E1663<>0),"GAP_DOWN",IF(AND($E1663>=$BD1663,$E1663<>0),"GAP_UP",IF(AND($G1663<=$BJ1663,$G1663<>0),"STOP",IF($BK1663=TRUE,"TARGET","")))))
=IF($BN1663="STOP",$BJ1663,IF($BN1663="TARGET",IF($BD1663>E1663,BD1663,E1663),IF(OR($BN1663="GAP_DOWN",$BN1663="GAP_UP"),E1663,"")))
=IF(ROW()=2,"",IF($BL1662=TRUE,$BP1662,IF($BI1663=TRUE,$E1664,"")))
=IF(ROW()=2,"",IF($BL1662=TRUE,$BQ1662,IF($BI1663=TRUE,$D1663,"")))
=IF(AND(BL1663=TRUE, BL1662=TRUE), MAX(H1663, BR1662), IF(AND(BL1663="", BR1662>0), MAX(H1663, BR1662), 0))
=IF(BL1663="",if(BR1663>0, (BR1663 - BO1663) / BR1663, 0),if(BR1663>0, (BR1663 - H1663) / BR1663, 0))
=IF(BR1663>0, IF(BR1662>0, MAX(BS1663, BT1662), BS1663), 0)
=IFERROR($H1663>INDEX($H:$H,ROW()-252),FALSE)
=IFERROR($H1663>INDEX($H:$H,ROW()-504),FALSE)
=IFERROR($H1663>=INDEX($H:$H,ROW()-756),FALSE)
=IF(ROW()-756<2,AND(BU1663,BV1663),(N(BU1663)+N(BV1663)+N(BW1663))>=2)
=BX1663
=IFERROR($H1663>=0.3*MAX($F$2:F1663),FALSE)
=IFERROR($H1663>=0.6*MAX(INDEX($F:$F,MAX(2,ROW()-756)):F1663),FALSE)
=IFERROR(ABS($H1663/AVERAGE(INDEX($H:$H,ROW()-99):$H1663)-1)>=$C$13,FALSE)
=IF(ROW()=2,$H1663>=0.3*MAX(INDEX($F:$F,MAX(2,ROW()-755)):F1663),AND(INDEX($CC:$CC,ROW()-1),$H1663>=0.3*MAX(INDEX($F:$F,MAX(2,ROW()-755)):F1663)))
=IF(ROW()<=1+$C$14,"",INDEX($AF:$AF,ROW()-$C$14))
=IF(ROW()<=1+$C$14,"",INDEX($AG:$AG,ROW()-$C$14))
=IF(ROW()<=1+$C$14,"",INDEX($AH:$AH,ROW()-$C$14))
=IF(ROW()=2,IF($CE1663="","",$CE1663),IF($CE1663<>"",$CE1663,CG1662))
=IF(ROW()=2,IF($CF1663="","",$CF1663),IF($CF1663<>"",$CF1663,CH1662))
=IF(ROW()=2,IF($CE1663="","",ROW()),IF($CE1663<>"",ROW(),CI1662))
=IF($CE1663<>"",CG1662,CJ1662)
=IF($CE1663<>"",CH1662,CK1662)
=IF($CE1663<>"",CI1662,CL1662)
=IF($CE1663<>"",CJ1662,CM1662)
=IF($CE1663<>"",CK1662,CN1662)
=IF($CE1663<>"",CL1662,CO1662)
=IF($CE1663<>"",CM1662,CP1662)
=IF($CE1663<>"",CN1662,CQ1662)
=IF($CE1663<>"",CO1662,CR1662)
=IF($CE1663<>"",CP1662,CS1662)
=IF($CE1663<>"",CQ1662,CT1662)
=IF($CE1663<>"",CR1662,CU1662)
=IF($CE1663<>"",CS1662,CV1662)
=IF($CE1663<>"",CT1662,CW1662)
=IF($CE1663<>"",CU1662,CX1662)
=IF($CE1663<>"",CV1662,CY1662)
=IF($CE1663<>"",CW1662,CZ1662)
=IF($CE1663<>"",CX1662,DA1662)
=IF($CE1663<>"",CY1662,DB1662)
=IF($CE1663<>"",CZ1662,DC1662)
=IF($CE1663<>"",DA1662,DD1662)
=IF(AND($F1663>=CG1663,$G1663<=CH1663),CG1663,IF(AND($F1663>=CJ1663,$G1663<=CK1663),CJ1663,IF(AND($F1663>=CM1663,$G1663<=CN1663),CM1663,IF(AND($F1663>=CP1663,$G1663<=CQ1663),CP1663,IF(AND($F1663>=CS1663,$G1663<=CT1663),CS1663,IF(AND($F1663>=CV1663,$G1663<=CW1663),CV1663,IF(AND($F1663>=CY1663,$G1663<=CZ1663),CY1663,IF(AND($F1663>=DB1663,$G1663<=DC1663),DB1663,""))))))))))
=IF(DE1663="","",IF(DE1663=CG1663,CH1663,IF(DE1663=CJ1663,CK1663,IF(DE1663=CM1663,CN1663,IF(DE1663=CP1663,CQ1663,IF(DE1663=CS1663,CT1663,IF(DE1663=CV1663,CW1663,IF(DE1663=CY1663,CZ1663,IF(DE1663=DB1663,DC1663,""))))))))) )
=IF(DE1663="","",IF(DE1663=CG1663,CI1663,IF(DE1663=CJ1663,CL1663,IF(DE1663=CM1663,CO1663,IF(DE1663=CP1663,CR1663,IF(DE1663=CS1663,CU1663,IF(DE1663=CV1663,CX1663,IF(DE1663=CY1663,DA1663,IF(DE1663=DB1663,DD1663,""))))))))) )
=IF(DE1663="","",IF(DE1663=CG1663,1,IF(DE1663=CJ1663,2,IF(DE1663=CM1663,3,IF(DE1663=CP1663,4,IF(DE1663=CS1663,5,IF(DE1663=CV1663,6,IF(DE1663=CY1663,7,IF(DE1663=DB1663,8,""))))))))) )
=AND($DE1663<>"",ROW()>$DG1663)
=AND($DI1663,OR($DI1662=FALSE,$DH1663<>$DH1662))
"""


def excel_col_to_num(col: str) -> int:
    """Excel column letters to 1-based number: A=1, Z=26, AA=27, ..."""
    col = col.upper()
    num = 0
    for ch in col:
        num = num * 26 + (ord(ch) - ord("A") + 1)
    return num


def excel_num_to_col(n: int) -> str:
    """1-based Excel column number to letters."""
    if n < 1:
        raise ValueError("n must be >= 1")
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(ord("A") + rem) + s
    return s


def extract_referenced_cols(formulas: str) -> set[str]:
    referenced: set[str] = set()

    # Whole column refs like $F:$F or $H:$H
    for m in re.finditer(r"\$([A-Z]{1,2})\s*:\s*\$([A-Z]{1,2})", formulas):
        referenced.add(m.group(1))
        referenced.add(m.group(2))

    # Ranges like $F$2:F1663 or $F:$F (cell/range parts captured by the cell regex below)
    # Absolute/relative cell refs like $F$1663 or F1663 or C$10
    patterns = [
        r"\$([A-Z]{1,2})\$?\d+",  # $F1663, $F$1663
        r"\b([A-Z]{1,2})\$\d+\b",  # C$10
        r"\b([A-Z]{1,2})\d+\b",  # F1663, N1663
    ]
    for pat in patterns:
        for m in re.finditer(pat, formulas):
            referenced.add(m.group(1))

    return referenced


def main() -> None:
    # We assume the provided header range ends at DJ (per your headers: "... First touch after availability").
    start = "D"
    end = "DJ"
    start_n = excel_col_to_num(start)
    end_n = excel_col_to_num(end)

    all_cols = {excel_num_to_col(i) for i in range(start_n, end_n + 1)}
    referenced = extract_referenced_cols(FORMULA_TEXT)

    unused = sorted(all_cols - referenced)
    print("Referenced column letters:", ", ".join(sorted(referenced)))
    print("\nUnused (never referenced anywhere in pasted formulas):")
    print(", ".join(unused))
    print(f"\nTotal unused count: {len(unused)} (out of {len(all_cols)} columns in D..DJ)")


if __name__ == "__main__":
    main()

