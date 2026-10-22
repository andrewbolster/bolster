import pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from bolster.data_sources import ons_cpi
from bolster.data_sources.health_ni import emergency_care_waiting_times as ed
from bolster.data_sources.nisra import ashe, births, marriages
OUT="/home/user/bolster/docs/insights/2026-10-22/img/"
ACC="#1f6f8b"; BG="#fcfcfb"
BOX=dict(boxstyle="round,pad=0.35", facecolor="#fcfcfb", alpha=0.85, edgecolor="none")
def style(ax,title,ylabel):
    ax.set_title(title,loc="left",fontsize=11); ax.set_ylabel(ylabel)
    ax.spines[["top","right"]].set_visible(False); ax.set_facecolor(BG); ax.figure.set_facecolor(BG); ax.grid(axis="y",alpha=.25)
pd.set_option("display.width",250,"display.max_rows",100)
# F1
d=ed.get_latest_data(); t1=d[(d.attendance_type=="Type 1")]
g=t1.groupby("date")[["under_4hrs","over_12hrs","total"]].sum()
g["p4"]=g.under_4hrs/g.total*100; g["o12"]=g.over_12hrs/g.total*100
sep=g[g.index.month==9]
print("F1 table (September, Type 1)"); print(sep[["total","p4","o12"]].round(1).assign(year=sep.index.year).set_index("year").to_string())
print("last 6 months"); print(g.tail(6)[["total","p4","o12"]].round(1).to_string())
fig,ax=plt.subplots(figsize=(7,3.6)); ax.plot(g.index,g.p4,color=ACC,lw=1.6)
style(ax,"Type 1 ED: share seen within 4 hours, NI, monthly","% of attendances")
ax.annotate(f"{g.p4.iloc[-1]:.1f}%",(g.index[-1],g.p4.iloc[-1]),xytext=(-38,12),textcoords="offset points",bbox=BOX)
ax.annotate(f"{g.p4.iloc[0]:.1f}%",(g.index[0],g.p4.iloc[0]),xytext=(8,-4),textcoords="offset points",bbox=BOX)
fig.tight_layout(); fig.savefig(OUT+"1-ed-four-hour.svg"); plt.close()
# site table
s=t1[t1.date.isin([pd.Timestamp("2025-09-01"),pd.Timestamp("2026-09-01")])].copy()
p=s.pivot_table(index="dept",columns="year",values=["under_4hrs","over_12hrs","total"],aggfunc="sum")
site=pd.DataFrame({"p4_2025":p["under_4hrs"][2025]/p["total"][2025]*100,"p4_2026":p["under_4hrs"][2026]/p["total"][2026]*100,"o12_2025":p["over_12hrs"][2025]/p["total"][2025]*100,"o12_2026":p["over_12hrs"][2026]/p["total"][2026]*100,"att_2026":p["total"][2026]}).round(1)
print(site.sort_values("p4_2026").to_string())
# F2
c=ons_cpi.get_latest_data("monthly"); cpi=c[(c.series=="D7BT")&(c.month==4)].set_index("year").value
a=ashe.get_latest_ashe_timeseries("weekly"); a=a[a.work_pattern=="All"].set_index("year").median_weekly_earnings
x=pd.DataFrame({"median_wk":a,"cpi_apr":cpi}).dropna(); x["real"]=x.median_wk/x.cpi_apr*x.cpi_apr.iloc[-1]
x["nom_yoy"]=x.median_wk.pct_change()*100; x["cpi_yoy"]=x.cpi_apr.pct_change()*100; x["real_yoy"]=x.real.pct_change()*100
print("F2"); print(x.loc[2007:].round(1).to_string())
fig,ax=plt.subplots(figsize=(7,3.6)); ax.plot(x.index,x.real,color=ACC,lw=1.6)
style(ax,"NI median weekly pay in April 2026 prices (CPI-deflated)","GBP per week")
ax.annotate(f"£{x.real.iloc[-1]:.0f}",(2026,x.real.iloc[-1]),xytext=(-48,-4),textcoords="offset points",bbox=BOX)
ax.annotate(f"£{x.real[2009]:.0f} (2009)",(2009,x.real[2009]),xytext=(6,8),textcoords="offset points",bbox=BOX)
ax.annotate(f"£{x.real[2014]:.0f} (2014)",(2014,x.real[2014]),xytext=(6,-22),textcoords="offset points",bbox=BOX)
fig.tight_layout(); fig.savefig(OUT+"2-real-pay.svg"); plt.close()
# F3
mr=marriages.get_latest_marriages().set_index("date").marriages.dropna().sort_index()
m12=mr.rolling(12).sum(); m12=m12[m12.index.month==9].dropna()
bb=births.get_latest_births()["registration"]; bb=bb[bb.sex=="Persons"].set_index("month").births.sort_index()
b12=bb.rolling(12).sum(); b12=b12[b12.index.month==9].dropna()
j=pd.DataFrame({"marriages":m12.rename(lambda t:t.year),"births":b12.rename(lambda t:t.year)}).dropna()
j["m_yoy"]=j.marriages.pct_change()*100; j["b_yoy"]=j.births.pct_change()*100
print("F3"); print(j.round(1).to_string())
print("corr yoy all",j[["m_yoy","b_yoy"]].corr().iloc[0,1].round(2))
k=j.drop([2020,2021,2022]).dropna(); print("corr yoy excl 2020-22",k[["m_yoy","b_yoy"]].corr().iloc[0,1].round(2), len(k))
fig,ax=plt.subplots(figsize=(7,3.6)); ax.plot(j.index,j.births,color=ACC,lw=1.6)
style(ax,"NI births registered, 12 months to September","births")
ax.annotate(f"{int(j.births.iloc[-1]):,}",(2026,j.births.iloc[-1]),xytext=(-50,10),textcoords="offset points",bbox=BOX)
ax.annotate(f"{int(j.births.max()):,} ({j.births.idxmax()})",(j.births.idxmax(),j.births.max()),xytext=(8,-16),textcoords="offset points",bbox=BOX)
fig.tight_layout(); fig.savefig(OUT+"3-births.svg"); plt.close()
