"""Synthetic fixture tests only: never reported as empirical model performance."""
from datetime import date,timedelta
import pandas as pd
from sports_betting_ai.model import train,load_model
import sports_betting_ai.model as model


def test_training_temporal_holdout(tmp_path,monkeypatch):
    monkeypatch.setattr(model, "available_names", lambda: ["rolling20"])
    rows=[]
    for i in range(100):
        for p in range(6):
            rows.append({"game_id":1000+i,"player_id":p,"game_date":(date(2025,1,1)+timedelta(days=i)).isoformat(),
                         "home": i%2,"minutes":30,"points":(12+i%4+p),
                         "rebounds":3+p%3,"assists":4+p%2})
    summary=train(pd.DataFrame(rows),str(tmp_path/"models"),min_rows=300,only=["player_points"])
    m=summary["player_points"]
    assert m["selected"]=="rolling20"
    assert m["test_start"]>="2025-01-01"
    assert m["n_train"] == 6*80
    assert load_model(str(tmp_path/"models"),"player_points") is not None
