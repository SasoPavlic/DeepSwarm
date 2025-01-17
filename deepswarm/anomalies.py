import numpy as np
import sklearn.metrics
from tensorflow.keras import backend as K
from deepswarm.log import Log
from . import data_config
import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve


def calculate_confusion_matrix(y_test, valid_label, anomaly_label, idxs):
    """Compute confusion matrix based on found anomalies in dataset
    Returns:
        Calculated metrics
    """
    all_anomalies = sum(x in anomaly_label for x in y_test)
    all_valid = sum(x in valid_label for x in y_test)
    instaces_in_quantile = np.array(y_test)[idxs.astype(int)]
    TP = sum(sum(x == anomaly_label for x in instaces_in_quantile))
    FN = all_anomalies - TP
    FP = len(idxs) - TP
    TN = all_valid - FP

    return (all_anomalies, all_valid, TP, FN, FP, TN)


def evaluate_anomalies(TP, FN, FP, TN):
    """Compute recall, precision and F1-score
    Returns:
        Recall, Precision, F1-score
    """
    recall = (TP / (TP + FN))
    precision = ((TP / (TP + FP)))
    F1 = 2 * ((precision * recall) / (precision + recall))
    return (round(recall, 3), round(precision, 3), round(F1, 3))


def calculate_roc_curve(model, x_test, y_test,
         manual_code=False,
         valid_label=data_config['valid_label'],
         anomaly_label=data_config['anomaly_label']):
    """Compute ROC-AUC values and visualize it in plot
    Returns:
        ROC curve on plot
    """

    decoded = model.predict(x_test)
    errors = []

    # loop over all original images and their corresponding
    # reconstructions
    for (image, recon) in zip(x_test, decoded):
        # compute the mean squared error between the ground-truth image
        # and the reconstructed image, then add it to our list of errors
        mse = np.mean((image - recon) ** 2)
        errors.append(mse)

    FPR_array = []
    TPR_array = []
    for quantile in np.linspace(0, 1, 100):
        thresh = np.quantile(errors, quantile)
        idxs = np.where(np.array(errors) >= thresh)[0]
        (all_anomalies, all_valid, TP, FN, FP, TN) = calculate_confusion_matrix(y_test,
                                                                                valid_label,
                                                                                anomaly_label,
                                                                                idxs)
        TPR = (TP / (TP + FN))
        FNR = (FN / (TP + FN))
        TNR = (TN / (TN + FP))
        FPR = 1 - TNR

        FPR_array.append(FPR)
        TPR_array.append(TPR)

    # https://www.analyticsvidhya.com/blog/2020/06/auc-roc-curve-machine-learning/
    random_probs = [0 for i in range(len(y_test))]
    p_fpr, p_tpr, thresholds = roc_curve(y_test, random_probs, pos_label=1)

    # This is the ROC curve
    plt.style.use('seaborn')

    # plot roc curves
    plt.plot(FPR_array, TPR_array, linestyle='--', color='green', label='Autoencoder')
    plt.plot(p_fpr, p_tpr, linestyle='--', color='blue')

    plt.title(f'ROC curve - AUC: {round(np.trapz(TPR_array, FPR_array), 3)}')
    # x label
    plt.xlabel('False Positive Rate')
    # y label
    plt.ylabel('True Positive rate')
    plt.legend(loc='best')

    auc = round(np.trapz(TPR_array, FPR_array), 3)

    if manual_code:
        print(f"=====================================")
        print(f"Model AUC score: {auc}")
    else:
        print(f"=====================================")
        Log.info(f"Model AUC score: {auc}")
    return plt


# Helpful tutorial https://www.pyimagesearch.com/2020/03/02/anomaly-detection-with-keras-tensorflow-and-deep-learning/
# TODO Refactor function to smaller components (threshold value, anomalies, evaluation metrics, results)
def find(model, x_test, y_test, quantile=0.99,
         manual_code=False,
         valid_label=data_config['valid_label'],
         anomaly_label=data_config['anomaly_label']):

    """Compute threshold for anomalies. Find anomalies in dataset. Evaluates model
    Returns:
        Plot of found anomalies
    """

    decoded = model.predict(x_test)
    errors = []

    # loop over all original images and their corresponding
    # reconstructions
    for (image, recon) in zip(x_test, decoded):
        # compute the mean squared error between the ground-truth image
        # and the reconstructed image, then add it to our list of errors
        mse = np.mean((image - recon) ** 2)
        errors.append(mse)

    # compute the q-th quantile of the errors which serves as our
    # threshold to identify anomalies -- any data point that our model
    # reconstructed with > threshold error will be marked as an outlier
    thresh = np.quantile(errors, quantile)
    idxs = np.where(np.array(errors) >= thresh)[0]


    (all_anomalies, all_valid, TP, FN, FP, TN) = calculate_confusion_matrix(y_test,
                                                                            valid_label,
                                                                            anomaly_label,
                                                                            idxs)
    (recall, precision, F1) = evaluate_anomalies(TP, FN, FP, TN)


    response_msg_0 = f"[INFO] Dataset has {len(y_test)} instances"
    response_msg_1 = f"[GOAL] Actual number of all anomalies in dataset: {all_anomalies}"
    response_msg_2 = f"[GOAL] Actual number of all valid labels in dataset: {all_valid}"
    response_msg_3 = f"[INFO] Model found: {len(idxs)} instances inside of quantile:{quantile}"
    response_msg_4 = f"[RESULT] Number of true positives anomalies found: {TP} instances inside of quantile:{quantile}"


    if manual_code:
        print(response_msg_0)
        print(response_msg_1)
        print(response_msg_2)
        print(response_msg_3)
        print(response_msg_4)

        print(f"Recall: {recall}")
        print(f"Precision: {precision}")
        print(f"F1 Score: {F1}")

    else:
        Log.info(response_msg_0)
        Log.info(response_msg_1)
        Log.info(response_msg_2)
        Log.info(response_msg_3)
        Log.info(response_msg_4)
        Log.info(f"Recall: {recall}")
        Log.info(f"Precision: {precision}")
        Log.info(f"F1 Score: {F1}")

    # initialize the outputs array
    outputs = None

    shuffler = np.random.permutation(len(idxs))
    idxs = idxs[shuffler]

    # loop over the indexes of images with a high mean squared error term
    # maximum allowed size of plot is limited, that is why we display only 150 images
    for i in idxs[:500]:
        # grab the original image and reconstructed image
        original = (x_test[i])
        recon = (decoded[i])

        # stack the original and reconstructed image side-by-side
        output = np.hstack([original, recon])

        # if the outputs array is empty, initialize it as the current
        # side-by-side image display

        if outputs is None:
            outputs = output

        # otherwise, vertically stack the outputs
        else:
            outputs = np.vstack([outputs, output])

    # show the output visualization

    vol_size = K.int_shape(outputs)
    final_output = outputs.reshape(vol_size[0], vol_size[1])
    plt.figure(figsize=(10, 100))
    plt.imshow(final_output)
    plt.title(f"(Anomaly detection)\n"
              f"Model found: {len(idxs)} instances inside of quantile:{quantile}\n"
              f"Number of true positives anomalies: {TP}\n"
              f"Valid label/s: {valid_label}\n"
              f"Anomaly label/s: {anomaly_label}")

    return plt
