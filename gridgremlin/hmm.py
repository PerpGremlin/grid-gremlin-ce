# K10: a hidden Markov model of a market's returns (research 2026-10-11,
# ops/research/hmm_regimes.py). A Gaussian HMM — each hidden state its own
# mean and volatility — fitted by Baum-Welch with scaled forward-backward
# passes. Pure maths, standard library only; nothing here reads a venue.
# The live reading (market.read_hmm) fits it daily and filters hourly; the
# filtered probability uses only the returns up to each moment.
import math
import random

VAR_FLOOR = 1e-10



def _pdf(x, mu, var):
    return math.exp(-(x - mu) ** 2 / (2 * var)) / math.sqrt(2 * math.pi * var)


def forward(obs, pi, A, mu, var):
    """Scaled forward pass: (alphas, log-likelihood). alphas[t][k] is
    P(state k at t | obs up to t) — the filtered probability, no lookahead."""
    K = len(pi)
    alphas, ll = [], 0.0
    prev = None
    for t, x in enumerate(obs):
        e = [_pdf(x, mu[k], var[k]) for k in range(K)]
        if prev is None:
            a = [pi[k] * e[k] for k in range(K)]
        else:
            a = [e[k] * sum(prev[j] * A[j][k] for j in range(K)) for k in range(K)]
        c = sum(a) or 1e-300
        a = [v / c for v in a]
        ll += math.log(c)
        alphas.append(a)
        prev = a
    return alphas, ll


def fit(obs, K, iters=150, tol=1e-6, seed=0):
    """Baum-Welch for a Gaussian HMM. Returns (pi, A, mu, var, log-likelihood),
    states sorted by volatility (0 = calmest)."""
    rng = random.Random(seed)
    n = len(obs)
    srt = sorted(obs, key=abs)
    mu = [0.0] * K
    var = []
    for k in range(K):                        # spread the starting volatilities by quantile
        part = srt[int(k * n / K):int((k + 1) * n / K)] or srt
        var.append(max(sum(x * x for x in part) / len(part) * rng.uniform(0.8, 1.25), VAR_FLOOR))
    A = [[(0.95 if i == j else 0.05 / (K - 1)) if K > 1 else 1.0 for j in range(K)] for i in range(K)]
    pi = [1.0 / K] * K
    last = -float('inf')
    for _ in range(iters):
        alphas, ll = forward(obs, pi, A, mu, var)
        # scaled backward pass
        betas = [[1.0] * K for _ in range(n)]
        for t in range(n - 2, -1, -1):
            e = [_pdf(obs[t + 1], mu[k], var[k]) for k in range(K)]
            b = [sum(A[j][k] * e[k] * betas[t + 1][k] for k in range(K)) for j in range(K)]
            s = sum(b) or 1e-300
            betas[t] = [v / s for v in b]
        gam = []
        for t in range(n):
            g = [alphas[t][k] * betas[t][k] for k in range(K)]
            s = sum(g) or 1e-300
            gam.append([v / s for v in g])
        xi_sum = [[0.0] * K for _ in range(K)]
        for t in range(n - 1):
            e = [_pdf(obs[t + 1], mu[k], var[k]) for k in range(K)]
            m = [[alphas[t][i] * A[i][j] * e[j] * betas[t + 1][j] for j in range(K)] for i in range(K)]
            s = sum(sum(r) for r in m) or 1e-300
            for i in range(K):
                for j in range(K):
                    xi_sum[i][j] += m[i][j] / s
        pi = gam[0][:]
        for i in range(K):
            row = sum(xi_sum[i]) or 1e-300
            A[i] = [v / row for v in xi_sum[i]]
        for k in range(K):
            w = sum(g[k] for g in gam) or 1e-300
            mu[k] = sum(g[k] * x for g, x in zip(gam, obs)) / w
            var[k] = max(sum(g[k] * (x - mu[k]) ** 2 for g, x in zip(gam, obs)) / w, VAR_FLOOR)
        if ll - last < tol:
            break
        last = ll
    order = sorted(range(K), key=lambda k: var[k])
    return ([pi[k] for k in order], [[A[i][j] for j in order] for i in order],
            [mu[k] for k in order], [var[k] for k in order], ll)


def best_fit(obs, K, restarts=3):
    return max((fit(obs, K, seed=s) for s in range(restarts)), key=lambda r: r[4])


def sample(pi, A, mu, var, n, rng):
    """Draw n observations from a known HMM: (obs, states)."""
    K = len(pi)
    s = rng.choices(range(K), weights=pi)[0]
    obs, states = [], []
    for _ in range(n):
        states.append(s)
        obs.append(rng.gauss(mu[s], math.sqrt(var[s])))
        s = rng.choices(range(K), weights=A[s])[0]
    return obs, states


def bic(ll, K, n):
    """Bayesian information criterion — lower is better; it charges each
    parameter (K-1 initial, K(K-1) transition, 2K emission)."""
    p = (K - 1) + K * (K - 1) + 2 * K
    return -2 * ll + p * math.log(n)
