import argparse
import numpy as np
from keras.wrappers.scikit_learn import KerasClassifier
from keras.callbacks import ModelCheckpoint, TensorBoard
from keras.models import load_model
from sklearn.model_selection import cross_val_score
from sklearn.model_selection import KFold
from sklearn.metrics import confusion_matrix
from phase_utils import print_cm
from phase_features_loader import PhaseFeaturesLoader
from phase_model_simple import model_simple
from phase_model_resnet import model_resnet

if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-a", "--action", choices=["train", "test"], default="train",
                        help="set the action, either training or test the dataset")
    parser.add_argument("--train_dataset", default="data/phase/ml_features_train.csv",
                        help="set the path to the training dataset")
    parser.add_argument("--test_dataset", default="data/phase/ml_features_test.csv",
                        help="set the path to the test dataset")
    parser.add_argument("-m", "--model", default=None,
                        help="set the path to the pre-trained model/weights")
    parser.add_argument("--cv", type=bool, default=False,
                        help="enable / disable a full cross validation with n_splits=10")
    parser.add_argument("-b", "--batch_size", type=int, default=256,
                        help="set the batch size)")
    parser.add_argument("-e", "--epochs", type=int, default=2000,
                        help="set the epochs number)")
    parser.add_argument("-l", "--layers", default="128 128 64 48 48 32 32 48 32 16",
                        help="set the hidden layers)")
    parser.add_argument("-d", "--dropout", type=float, default=0.1,
                        help="set the dropout)")
    parser.add_argument("-s", "--stations", default="URZ",
                        help="set the station name, it supports currently only LPAZ and URZ")
    parser.add_argument("-v", "--verbose", type=int, default=0,
                        help="set the verbosity)")
    parser.add_argument("-p", "--phase_length", default="URZ 6840 6840 6840 20520",
                        help="set the number of entries of phases per stations to be read from the dataset.\n" +
                             "The default is for the training, for the test use 'URZ 2280 2280 2280 6840, " +
                             "LPAZ 160 160 160 480'")

    args = parser.parse_args()

    # fix random seed for reproducibility
    seed = 7
    np.random.seed(seed)

    epochs = args.epochs
    train_dataset = args.train_dataset
    test_dataset = args.test_dataset
    phase_length = {}
    try:
        for p in args.phase_length.split(","):
            s = p.strip().split(" ")
            phase_length.update({s[0]:{"regP": int(s[1]), "regS": int(s[2]), "tele": int(s[3]), "N": int(s[4])}})
    except ValueError:
        print("It should be a list of a station name followed by four numbers.")
        exit(1)
    stations_lower = [station.lower() for station in sorted(phase_length.keys())]
    layers = []
    try:
        layers = [int(units) for units in args.layers.split(" ")]
    except ValueError:
        print("The layers should be a list of integer, delimited by a whitespace")
        exit(1)

    dropout = args.dropout
    batch_size = args.batch_size
    validation_split = 0.1
    if args.model is None:
        model_file_path = "results/phase_weights_best_s_{}_l_{}_d_{}.hdf5".\
            format("_".join(stations_lower), "_".join([str(layer) for layer in layers]), dropout)
    else:
        model_file_path = args.model

    model = model_resnet

    if args.action == "train":
        # load train dataset
        pd = PhaseFeaturesLoader(filename=train_dataset, validation_split=validation_split,
                                 phase_length=phase_length, batch_size=batch_size)
        tensorboard = TensorBoard(log_dir='graph', histogram_freq=0, write_graph=True, write_images=True)
        checkpoint = ModelCheckpoint(model_file_path, monitor='acc', verbose=args.verbose,
                                     save_best_only=True, mode='max')
        if args.cv:
            train_x, train_y = pd.get_dataset()
            kfold = KFold(n_splits=10, shuffle=True, random_state=seed)
            estimator = KerasClassifier(build_fn=model, layers=layers, dropout=dropout,
                                        epochs=epochs, batch_size=500, verbose=args.verbose)
            results = cross_val_score(estimator, train_x, train_y, cv=kfold,
                                      fit_params={'callbacks':[checkpoint, tensorboard]})

            print("Baseline: %.2f%% (%.2f%%)" % (results.mean()*100, results.std()*100))
        else:
            model = model(layers=layers, dropout=dropout, layer_number=10)
            print(model.summary())
            class_weight = {0:1, 1:1, 2:1, 3:1}
            history = model.fit_generator(generator = pd.generate("train"),
                                steps_per_epoch = pd.get_len("train")//batch_size,
                                validation_data = pd.generate("validation"),
                                validation_steps = pd.get_len("validation")//batch_size,
                                use_multiprocessing=True, class_weight=None,
                                epochs=epochs, verbose=args.verbose, callbacks=[checkpoint, tensorboard])
            print("Max of acc: {}, val_acc: {}".
                  format(max(history.history["acc"]), max(history.history["val_acc"])))
            print("Min of loss: {}, val_loss: {}".
                  format(min(history.history["loss"]), min(history.history["val_loss"])))
    else:
        # load test dataset
        pd = PhaseFeaturesLoader(filename=test_dataset, phase_length=phase_length, batch_size=batch_size)
        test_x, test_y = pd.get_dataset()

        # load model & weight
        loaded_model = load_model(model_file_path)
        print("Loaded model from disk")

        # evaluate loaded model on test data
        loaded_model.compile(loss='categorical_crossentropy', optimizer='adam', metrics=['accuracy'])
        score = loaded_model.evaluate(test_x, test_y, verbose=0)
        prediction = loaded_model.predict(test_x, verbose=0)
        print("%s: %.2f%%" % (loaded_model.metrics_names[1], score[1]*100))
        print("Confusion matrix:")
        phases = ['regP', 'regS', 'tele', 'N']
        cm = confusion_matrix(test_y.argmax(axis=1), prediction.argmax(axis=1))
        print_cm(cm, labels=phases)