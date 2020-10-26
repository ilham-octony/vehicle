from utils import utils
import os
import logging
import logging.handlers
import random
import numpy as np
import skvideo.io
import cv2
import matplotlib.pyplot as plt
import csv


cv2.ocl.setUseOpenCL(False)
random.seed(123)

from infrastructure import (
    PipelineRunner,
    ContourDetection,
    Visualizer,
    VehicleCounter)

# ============================================================================
SAVE_IMAGE = False
IMAGE_DIR = "./out"
VIDEO_SOURCE = "videos/Ciaul 08.30 20200930 Jam Normal.mkv"
SHAPE = (576, 720)  # HxW
EXIT_PTS = np.array([
    [[643, 421], [128, 450], [150, 575], [720, 576]],
    [[643, 421], [719, 469], [720, 576], [720, 576]],
    [[0, 0], [0, 0], [0, 0], [0, 0]]
])
# ============================================================================

def train_bg_subtractor(inst, cap, num=500):
    print ('Please wait, training is on progress!')
    i = 0
    for frame in cap:
        inst.apply(frame, None, 0.001)
        i += 1
        if i >= num:
            return cap


def main():
    log = logging.getLogger("main")

    init = True
    if(init):
        #initialize .csv
	    with open('traffic_measurement.csv', 'w') as f:
		    writer = csv.writer(f)
		    csv_line = "TimeStamp, Vehicle Movement Direction, Vehicle Speed (km/h)"
		    writer.writerows([csv_line.split(',')])
	    init = False

    base = np.zeros(SHAPE + (3,), dtype='uint8')
    exit_mask = cv2.fillPoly(base, EXIT_PTS, (255, 255, 255))[:, :, 0]

    bg_subtractor = cv2.createBackgroundSubtractorMOG2(
        history=500, detectShadows=True)


    pipeline = PipelineRunner(pipeline=[
        ContourDetection(bg_subtractor=bg_subtractor,
                         save_image=SAVE_IMAGE, image_dir=IMAGE_DIR),
        VehicleCounter(exit_masks=[exit_mask], y_weight=2.0),
        Visualizer(image_dir=IMAGE_DIR)
    ], log_level=logging.DEBUG)

    cap = skvideo.io.vreader(VIDEO_SOURCE)
    
    train_bg_subtractor(bg_subtractor, cap, num=2400)

    _frame_number = -1
    frame_number = -1
    for frame in cap:
        if not frame.any():
            log.error("Frame capture failed, stopping...")
            break

        _frame_number += 1
        frame_number += 1

        pipeline.set_context({
            'frame': frame,
            'frame_number': frame_number,
        })
        pipeline.run()
	

if __name__ == "__main__":

    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

    main()
