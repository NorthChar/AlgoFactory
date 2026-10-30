from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


def build_pipeline(config):
    preprocess = ColumnTransformer([
        ("text", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000), config["text_features"][0])
    ])
    model = LogisticRegression(C=1.0, max_iter=500, random_state=config["seed"])
    return Pipeline([("preprocess", preprocess), ("model", model)])
