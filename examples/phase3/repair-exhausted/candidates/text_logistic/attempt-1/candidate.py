from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline


def build_pipeline(config):
    preprocess = ColumnTransformer([
        ("text", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000), config["text_features"][0])
    ])
    model = LinearSVC(C=4.0, max_iter=501, random_state=config["seed"])
    return Pipeline([("preprocess", preprocess), ("model", model)])
