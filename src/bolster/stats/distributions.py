import warnings
from time import time

import numpy as np
import pandas as pd
import scipy.stats as st
from tqdm.auto import tqdm


# Create models from data https://stackoverflow.com/questions/6620471/fitting-empirical-distribution-to-theoretical-ones-with-scipy-python
def best_fit_distribution(
    data, bins=200, ax=None, include_slow=False, discriminator="sse"
):
    """Model data by finding best fit distribution to data"""
    # Get histogram of original data
    y, x = np.histogram(data, bins=bins, density=True)
    x = (x + np.roll(x, -1))[:-1] / 2.0

    # Distributions to check
    DISTRIBUTIONS = [
        st.alpha,
        st.anglit,
        st.arcsine,
        st.beta,
        st.betaprime,
        st.bradford,
        st.burr,
        st.cauchy,
        st.chi,
        st.chi2,
        st.cosine,
        st.dgamma,
        st.dweibull,
        st.erlang,
        st.expon,
        st.exponnorm,
        st.exponweib,
        st.exponpow,
        st.f,
        st.fatiguelife,
        st.fisk,
        st.foldcauchy,
        st.foldnorm,
        st.frechet_r,
        st.frechet_l,
        st.genlogistic,
        st.genpareto,
        st.gennorm,
        st.genexpon,
        st.genextreme,
        st.gausshyper,
        st.gamma,
        st.gengamma,
        st.genhalflogistic,
        st.gilbrat,
        st.gompertz,
        st.gumbel_r,
        st.gumbel_l,
        st.halfcauchy,
        st.halflogistic,
        st.halfnorm,
        st.halfgennorm,
        st.hypsecant,
        st.invgamma,
        st.invgauss,
        st.invweibull,
        st.johnsonsb,
        st.johnsonsu,
        st.ksone,
        st.kstwobign,
        st.laplace,
        st.levy,
        st.levy_l,
        st.logistic,
        st.loggamma,
        st.loglaplace,
        st.lognorm,
        st.lomax,
        st.maxwell,
        st.mielke,
        st.nakagami,
        st.ncx2,
        st.ncf,
        st.nct,
        st.norm,
        st.pareto,
        st.pearson3,
        st.powerlaw,
        st.powerlognorm,
        st.powernorm,
        st.rdist,
        st.reciprocal,
        st.rayleigh,
        st.rice,
        st.recipinvgauss,
        st.semicircular,
        st.t,
        st.triang,
        st.truncexpon,
        st.truncnorm,
        st.tukeylambda,
        st.uniform,
        st.vonmises,
        st.vonmises_line,
        st.wald,
        st.weibull_min,
        st.weibull_max,
        st.wrapcauchy,
    ]
    SLOW_DISTRIBUTIONS = [st.levy_stable]

    if include_slow:
        DISTRIBUTIONS += SLOW_DISTRIBUTIONS

    # Best holders
    best_distribution = st.norm
    best_params = (0.0, 1.0)
    best_discriminator_value = np.inf

    times = {}

    # Estimate distribution parameters from data
    for distribution in tqdm(DISTRIBUTIONS):

        # Try to fit the distribution
        try:
            # Ignore warnings from data that can't be fit
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore")

                # fit dist to data
                start = time()
                print(distribution.name, end=" ")
                params = distribution.fit(data)
                times[distribution.name] = time() - start
                print(f"took {int(times[distribution.name])}")

                # Separate parts of parameters
                arg = params[:-2]
                loc = params[-2]
                scale = params[-1]

                if discriminator == "sse":
                    # Calculate fitted PDF and error with fit in distribution
                    pdf = distribution.pdf(x, loc=loc, scale=scale, *arg)
                    discriminator_value = np.sum(np.power(y - pdf, 2.0))
                else:
                    raise RuntimeError(
                        "You didn't finish this and you were planning on doing KS discrimination next"
                    )

                # if axis pass in add to plot
                try:
                    if ax:
                        pd.Series(pdf, x).plot(ax=ax)
                except Exception:
                    pass

                # identify if this distribution is better
                if best_discriminator_value > discriminator_value > 0:
                    best_distribution = distribution
                    best_params = params
                    best_discriminator_value = discriminator_value
                    print(
                        f"New best, {distribution.name} and got an sse of {discriminator_value}"
                    )

        except Exception:
            pass

    return (best_distribution.name, best_params)
