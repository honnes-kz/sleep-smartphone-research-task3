"""Figures based only on published aggregate statistics (not fabricated participant rows)."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
OUT=Path("reports/figures")
COLORS={"Social media":"#0072B2","Game apps":"#D55E00","Video player":"#009E73"}
MARKERS={"Social media":"o","Game apps":"s","Video player":"^"}

def save(fig,name):
    OUT.mkdir(parents=True,exist_ok=True)
    fig.savefig(OUT/f"{name}.png",dpi=300,bbox_inches="tight")
    fig.savefig(OUT/f"{name}.pdf",bbox_inches="tight")
    plt.close(fig)

def make_all():
    usage=pd.read_csv("data/processed/app_usage_summary.csv")
    eff=pd.read_csv("data/processed/app_effects_summary.csv")
    phone=pd.read_csv("data/processed/phone_effects_summary.csv")
    plt.rcParams.update({"axes.spines.top":False,"axes.spines.right":False,"font.size":10})
    # Fig 1: mean app-use minutes and SD
    fig,ax=plt.subplots(figsize=(8,4.8))
    frames=["Daytime","Pre-bedtime","Post-bedtime"]
    x=np.arange(len(frames)); width=.23
    for i,cat in enumerate(["Social media","Game apps","Video player"]):
        g=usage[usage.app_category==cat].set_index("timeframe").loc[frames]
        ax.bar(x+(i-1)*width,g.mean_minutes,width,yerr=g.sd_minutes,capsize=3,label=cat,color=COLORS[cat],edgecolor="black",linewidth=.4)
    ax.set_xticks(x,frames); ax.set_ylabel("Mean app use (minutes; SD error bars)"); ax.set_title("Smartphone app use by time of day")
    ax.legend(frameon=False,ncol=3,loc="upper left"); fig.tight_layout(); save(fig,"fig1_app_usage")
    # Fig 2: app-specific within-person standardized effects and published 95% credible intervals
    fig,ax=plt.subplots(figsize=(8,5.4)); y=np.arange(len(eff))
    for i,row in eff.iterrows():
        c=COLORS[row.app_category]
        ax.errorbar(row.within_person_beta,y[i],xerr=[[row.within_person_beta-row.ci95_low],[row.ci95_high-row.within_person_beta]],fmt=MARKERS[row.app_category],color=c,capsize=3,markersize=6)
    ax.axvline(0,color="black",linewidth=1,linestyle="--")
    labels=[f"{r.app_category} — {r.timeframe}" for r in eff.itertuples()]
    ax.set_yticks(y,labels); ax.invert_yaxis(); ax.set_xlabel("Standardized within-person effect (β; 95% credible interval)")
    ax.set_title("App-specific associations with daily sleep quality")
    ax.grid(axis="x",alpha=.2); fig.tight_layout(); save(fig,"fig2_app_effects")
    # Fig 3: smartphone timeframe effects
    fig,ax=plt.subplots(figsize=(7,4.2)); y=np.arange(len(phone))
    ax.errorbar(phone.within_person_beta,y,xerr=[phone.within_person_beta-phone.ci95_low,phone.ci95_high-phone.within_person_beta],fmt="o",color="#332288",capsize=4,markersize=7)
    ax.axvline(0,color="black",linestyle="--",linewidth=1)
    ax.set_yticks(y,phone.timeframe); ax.invert_yaxis(); ax.set_xlabel("Standardized within-person effect (β; 95% credible interval)")
    ax.set_title("Smartphone use and sleep quality: timeframe comparison"); ax.grid(axis="x",alpha=.2)
    fig.tight_layout(); save(fig,"fig3_phone_effects")

if __name__=="__main__":
    make_all(); print("Figures saved to",OUT)
