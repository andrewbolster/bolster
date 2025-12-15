import warnings
from time import time

import numpy as np
import pandas as pd
import scipy.stats as st
from tqdm.auto import tqdm


def _get_available_distributions(include_slow=False):
    """Get list of available scipy.stats distributions, filtering out incompatible ones."""
    # Define distributions that should be available in most scipy versions
    distribution_names = [
        "alpha",
        "anglit",
        "arcsine",
        "beta",
        "betaprime",
        "bradford",
        "burr",
        "cauchy",
        "chi",
        "chi2",
        "cosine",
        "dgamma",
        "dweibull",
        "erlang",
        "expon",
        "exponnorm",
        "exponweib",
        "exponpow",
        "f",
        "fatiguelife",
        "fisk",
        "foldcauchy",
        "foldnorm",
        "genlogistic",
        "genpareto",
        "gennorm",
        "genexpon",
        "genextreme",
        "gausshyper",
        "gamma",
        "gengamma",
        "genhalflogistic",
        "gilbrat",
        "gompertz",
        "gumbel_r",
        "gumbel_l",
        "halfcauchy",
        "halflogistic",
        "halfnorm",
        "halfgennorm",
        "hypsecant",
        "invgamma",
        "invgauss",
        "invweibull",
        "johnsonsb",
        "johnsonsu",
        "ksone",
        "kstwobign",
        "laplace",
        "levy",
        "levy_l",
        "logistic",
        "loggamma",
        "loglaplace",
        "lognorm",
        "lomax",
        "maxwell",
        "mielke",
        "nakagami",
        "ncx2",
        "ncf",
        "nct",
        "norm",
        "pareto",
        "pearson3",
        "powerlaw",
        "powerlognorm",
        "powernorm",
        "rdist",
        "reciprocal",
        "rayleigh",
        "rice",
        "recipinvgauss",
        "semicircular",
        "t",
        "triang",
        "truncexpon",
        "truncnorm",
        "tukeylambda",
        "uniform",
        "vonmises",
        "vonmises_line",
        "wald",
        "weibull_min",
        "weibull_max",
        "wrapcauchy",
    ]

    # Filter to only include distributions that actually exist in current scipy version
    available_distributions = []
    for name in distribution_names:
        if hasattr(st, name):
            available_distributions.append(getattr(st, name))

    slow_distributions = []
    if hasattr(st, "levy_stable"):
        slow_distributions.append(st.levy_stable)

    if include_slow:
        available_distributions.extend(slow_distributions)

    return available_distributions


# Create models from data https://stackoverflow.com/questions/6620471/fitting-empirical-distribution-to-theoretical-ones-with-scipy-python
def best_fit_distribution(data, bins=200, ax=None, include_slow=False, discriminator="sse"):
    """Model data by finding best fit distribution to data"""
    # Get histogram of original data
    y, x = np.histogram(data, bins=bins, density=True)
    x = (x + np.roll(x, -1))[:-1] / 2.0

    # Get available distributions for current scipy version
    DISTRIBUTIONS = _get_available_distributions(include_slow)

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
                    raise RuntimeError("You didn't finish this and you were planning on doing KS discrimination next")

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
                    print(f"New best, {distribution.name} and got an sse of {discriminator_value}")

        except Exception:
            pass

    return (best_distribution.name, best_params)
