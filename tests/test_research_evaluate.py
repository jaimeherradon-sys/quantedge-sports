"""Only mathematical sanity checks; never fictitious NBA performance."""
import numpy as np
from research.evaluate_history import calibration, probability, score

def test_research_count_probabilities():
    means=np.array([2.0, 9.0, 18.0])
    p=probability(means,9.5,0.0)
    assert 0<p[0]<p[1]<p[2]<1
    nb=probability(means,9.5,0.2)
    assert np.isfinite(nb).all() and ((nb>=0)&(nb<=1)).all()

def test_calibration_metrics_valid():
    p=np.array([0.1,0.25,0.65,0.85])
    outcome=np.array([0,1,1,1])
    ece,bins=calibration(p,outcome)
    assert 0<=ece<=1 and sum(b['count'] for b in bins)==4
    result=score(np.array([0,1,4,5]),np.array([0,1,3.5,5]),p,1.5)
    assert result['n']==4
    assert np.isfinite(result['brier']) and np.isfinite(result['log_loss'])
