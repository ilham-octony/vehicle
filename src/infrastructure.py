from utils import utils
import os
import logging
import csv
import os
import numpy as np
import cv2
import datetime
import csv

DIVIDER_COLOUR = (0, 0, 0)
BOUNDING_BOX_COLOUR = (0, 255, 0) # green
CENTROID_COLOUR = (255, 0, 0) # blue
CAR_COLOURS = [(0, 255, 255)] # yellow
EXIT_COLOR = (45, 45, 255) # red
current_path = os.getcwd() #get current path to save detected vehicle images
vehicle_count = [0]
speed_cache = ["n.a"]
direction_cache = ["n.a."]

class PipelineRunner(object):  
  
    def __init__(self, pipeline=None, log_level=logging.DEBUG):
        self.pipeline = pipeline or []
        self.context = {}
        self.log = logging.getLogger(self.__class__.__name__)
        self.log.setLevel(log_level)
        self.log_level = log_level
        self.set_log_level()

    def set_context(self, data):
        self.context = data

    def add(self, processor):
        if not isinstance(processor, PipelineProcessor):
            raise Exception(
                'Processor should be an isinstance of PipelineProcessor.')
        processor.log.setLevel(self.log_level)
        self.pipeline.append(processor)

    def remove(self, name):
        for i, p in enumerate(self.pipeline):
            if p.__class__.__name__ == name:
                del self.pipeline[i]
                return True
        return False

    def set_log_level(self):
        for p in self.pipeline:
            p.log.setLevel(self.log_level)

    def run(self):
        for p in self.pipeline:
            self.context = p(self.context)

        return self.context


class PipelineProcessor(object):

    def __init__(self):
        self.log = logging.getLogger(self.__class__.__name__)


class ContourDetection(PipelineProcessor):    

    def __init__(self, bg_subtractor, min_contour_width=35, min_contour_height=35, save_image=False, image_dir='images'):
        super(ContourDetection, self).__init__()

        self.bg_subtractor = bg_subtractor
        self.min_contour_width = min_contour_width
        self.min_contour_height = min_contour_height
        self.save_image = save_image
        self.image_dir = image_dir

    def filter_mask(self, img, a=None):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))

        # Fill any small holes
        closing = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
        # Remove noise
        opening = cv2.morphologyEx(closing, cv2.MORPH_OPEN, kernel)

        # Dilate to merge adjacent blobs
        dilation = cv2.dilate(opening, kernel, iterations=2)

        return dilation

    def detect_vehicles(self, fg_mask, context):

        matches = []

        # finding external contours
        contours, hierarchy = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_L1)

        for (i, contour) in enumerate(contours):
            (x, y, w, h) = cv2.boundingRect(contour)
            contour_valid = (w >= self.min_contour_width) and (
                h >= self.min_contour_height)

            if not contour_valid:
                continue

            centroid = utils.get_centroid(x, y, w, h)

            matches.append(((x, y, w, h), centroid))

        return matches

    def __call__(self, context):
        frame = context['frame'].copy()
        frame_number = context['frame_number']

        fg_mask = self.bg_subtractor.apply(frame, None, 0.001)
        # just thresholding values
        fg_mask[fg_mask < 240] = 0
        fg_mask = self.filter_mask(fg_mask, frame_number)

        if self.save_image:
            utils.save_frame(fg_mask, self.image_dir +
                             "/mask_%04d.png" % frame_number, flip=False)

        context['objects'] = self.detect_vehicles(fg_mask, context)
        context['fg_mask'] = fg_mask

        return context


class VehicleCounter(PipelineProcessor):

    def __init__(self, exit_masks=[], path_size=10, max_dst=30, x_weight=1.0, y_weight=1.0):
        super(VehicleCounter, self).__init__()

        self.exit_masks = exit_masks

        self.vehicle_count = 0
        self.car = 0
        self.motor = 0
        self.path_size = path_size
        self.pathes = []
        self.max_dst = max_dst
        self.x_weight = x_weight
        self.y_weight = y_weight

    def check_exit(self, point):
        for exit_mask in self.exit_masks:
            try:
                if exit_mask[point[1]][point[0]] == 255:
                    return True
            except:
                return True
        return False


    def check_exit2(self, point, exit_masks=[]):
        for exit_mask in exit_masks:
            if exit_mask[point[1]][point[0]] == 255:
                return True
        return False

    def __call__(self, context):
        objects = context['objects']
        context['exit_masks'] = self.exit_masks
        context['pathes'] = self.pathes
        context['vehicle_count'] = self.vehicle_count
        context['car'] = self.car
        context['motor'] = self.motor
        if not objects:
            return context

        points = np.array(objects)[:, 0:2]
        points = points.tolist()

        if not self.pathes:
            for match in points:
                self.pathes.append([match])

        else:
            new_pathes = []

            for path in self.pathes:
                _min = 999999
                _match = None
                for p in points:
                    if len(path) == 1:                        
                        d = utils.distance(p[0], path[-1][0])
                    else:
                        xn = 2 * path[-1][0][0] - path[-2][0][0]
                        yn = 2 * path[-1][0][1] - path[-2][0][1]
                        d = utils.distance(
                            p[0], (xn, yn),
                            x_weight=self.x_weight,
                            y_weight=self.y_weight
                        )

                    if d < _min:
                        _min = d
                        _match = p

                if _match and _min <= self.max_dst:
                    points.remove(_match)
                    path.append(_match)
                    new_pathes.append(path)

                if _match is None:
                    new_pathes.append(path)

            self.pathes = new_pathes

            if len(points):
                for p in points:
                    if self.check_exit(p[1]):
                        continue
                    self.pathes.append([p])

        for i, _ in enumerate(self.pathes):
            self.pathes[i] = self.pathes[i][self.path_size * -1:]

        new_pathes = []
        for i, path in enumerate(self.pathes):
            d = path[-2:]

            if (
                len(d) >= 2 and
                not self.check_exit(d[0][1]) and
                self.check_exit(d[1][1]) and
                self.path_size <= len(path)
            ):
                self.vehicle_count += 1 # a47
                vehicle_count[0] = self.vehicle_count
                img = context['frame']
                contour, centroid = path[-1][:2]
                x, y, w, h = contour
                list_type = ['Car', 'Motorcycle']
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                cv2.imwrite(current_path + "/detected_vehicles/vehicle" + str(vehicle_count[0]) + ".png", img[y:y + h - 1, x:x+w])
                if w < 90 :
                    self.motor += 1
                else :
                    self.car +=1

                #HEURISTIC SPEED PREDICTION
            
                for i, path in enumerate(context['pathes']):
                    path = np.array(path)[:, 1].tolist()
                    #print str(len(path))
                    if(path[len(path)-1][1]-path[len(path)-2][1] < 0 ):
                        speed = abs(path[len(path)-1][1]-path[len(path)-2][1])*10
                        if(speed == 0):
                            print("				was not be predicted")
                            speed_cache[0] = "n.a."
                            direction_cache[0] = "n.a."
                            if w < 90 :
                                print('type : ', list_type[1])
                            else :
                                print('type : ', list_type[0])
                        else:
                            if(path[len(path)-1][0] > 250):
                                speed = speed*3/4
                                speed_cache[0] = speed
                                direction_cache[0] = "Meningkat"
                            if (speed < 100):
                                print ("				SPEED (Meningkat): " + str(speed))
                                speed_cache[0] = speed
                                direction_cache[0] = "Meningkat"
                                if w < 90 :
                                    print('type : ', list_type[1])
                                else :
                                    print('type : ', list_type[0])
                            else:
                                speed = speed/5*3
                                if(speed > 100):
                                    speed = speed/5*3
                                    speed_cache[0] = speed
                                    direction_cache[0] = "Meningkat"
                                    print ("				SPEED (Meningkat): " + str(speed))
                                    if w < 90 :
                                        print('type : ', list_type[1])
                                    else :
                                        print('type : ', list_type[0])
                                else:
                                    print ("				SPEED (Meningkat): " + str(speed))
                                    speed_cache[0] = speed	
                                    direction_cache[0] = "Meningkat"
                                    if w < 90 :
                                        print('type : ', list_type[1])
                                    else :
                                        print('type : ', list_type[0])
                                    
                    else:
                        speed = abs(path[len(path)-1][1]-path[len(path)-2][1])
                        if (speed <3):
                            speed = speed*24
                        else:
                            speed = speed*12
                            
                        if(speed == 0):
                            print("was not be predicted")
                            print('box size :', w)
                            speed_cache[0] = "n.a"
                            direction_cache[0] = "Menurun"
                            if w < 90 :
                                print('type : ', list_type[1])
                            else :
                                print('type : ', list_type[0])
                        elif (speed < 100):
                            print ("SPEED (Menurun): " + str(speed))
                            print('box size :', w)
                            speed_cache[0] = speed
                            direction_cache[0] = "Menurun"
                            if w < 90 :
                                print('type : ', list_type[1])
                            else :
                                print('type : ', list_type[0])
                        else:
                            speed = speed/5*3
                            if(speed > 100):
                                speed = speed/5*3
                                speed_cache[0] = speed
                                direction_cache[0] = "Menurun"
                                print ("SPEED (Menurun): " + str(speed))
                                if w < 90 :
                                    print('type : ', list_type[1])
                                else :
                                    print('type : ', list_type[0])
                            else:
                                print ("SPEED (Menurun): " + str(speed))
                                speed_cache[0] = direction_cache[0] = "n.a."
                                if w < 90 :
                                    print('type : ', list_type[1])
                                else :
                                    print('type : ', list_type[0])
            
                for point in path:
                    cv2.circle(img, point, 2, CAR_COLOURS[0], -1) # a47
                    cv2.polylines(img, [np.int32(path)], False, CAR_COLOURS[0], 1)
                    time_stamp = str(datetime.datetime.now())
                    direction = str(direction_cache[0])
                    speed = str(speed_cache[0])
                    csv_line = time_stamp + "," + direction + "," + speed
                    with open('traffic_measurement.csv', 'a') as f:
                        writer = csv.writer(f)
                        writer.writerows([csv_line.split(',')])	
		#HEURISTIC SPEED PREDICTION				
            else:
                add = True
                for p in path:
                    if self.check_exit(p[1]):
                        add = False
                        break
                if add:
                    new_pathes.append(path)

        self.pathes = new_pathes

        context['pathes'] = self.pathes
        context['objects'] = objects
        context['vehicle_count'] = self.vehicle_count
	
        return context

class Visualizer(PipelineProcessor):   

    def __init__(self, save_image=False, image_dir='images'):
        super(Visualizer, self).__init__()

        self.save_image = save_image
        self.image_dir = image_dir

    def check_exit(self, point, exit_masks=[]):
        for exit_mask in exit_masks:
            if exit_mask[point[1]][point[0]] == 255:
                return True
        return False

    def draw_pathes(self, img, pathes):
        if not img.any():
            return

        for i, path in enumerate(pathes):
            path = np.array(path)[:, 1].tolist()
            for point in path:
                cv2.circle(img, point, 2, CAR_COLOURS[0], -1) # a47
                cv2.polylines(img, [np.int32(path)], False, CAR_COLOURS[0], 1)
		
        return img

    def draw_boxes(self, img, pathes, exit_masks=[]):
        for (i, match) in enumerate(pathes):

            contour, centroid = match[-1][:2]
            if self.check_exit(centroid, exit_masks):
                continue

            x, y, w, h = contour
            '''
            list_type = ['Car', 'Motorcycle']
            if w < 90 :
                cv2.putText(img, list_type[1], (int(x + w/2), int(y-5)),cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 0, 0), 2)
            else :
                cv2.putText(img, list_type[0], (int(x + w/2), int(y-5)),cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
            '''
            
            cv2.rectangle(img, (x, y), (x + w - 1, y + h - 1), BOUNDING_BOX_COLOUR, 2) #a47
            cv2.circle(img, centroid, 2, CENTROID_COLOUR, -1)
            
        return img

    def draw_ui(self, img, vehicle_count, car, motor, exit_masks=[]):

        for exit_mask in exit_masks:
            _img = np.zeros(img.shape, img.dtype)
            _img[:, :] = EXIT_COLOR
            mask = cv2.bitwise_and(_img, _img, mask=exit_mask)
            cv2.addWeighted(mask, 1, img, 1, 0, img)

        

        return img

    def __call__(self, context):		

        frame = context['frame'].copy()
        frame_number = context['frame_number']
        pathes = context['pathes']
        exit_masks = context['exit_masks']
        vehicle_count = context['vehicle_count']
        car = context['car']
        motor = context['motor']

        frame = self.draw_ui(frame, vehicle_count, car, motor, exit_masks)
        frame = self.draw_pathes(frame, pathes)
        frame = self.draw_boxes(frame, pathes, exit_masks)
        if self.save_image:
            utils.save_frame(frame, self.image_dir + "/processed_%04d.png" % frame_number)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.rectangle(frame, (686, 90), (389, 206), (255, 255, 255), -1)
        cv2.putText(frame,"INFORMASI LALU LINTAS", (393, 108), font, 0.6, (0,0, 0), 1,cv2.FONT_HERSHEY_SIMPLEX)
        cv2.putText(frame, ("- Jumlah Kendaraan: {total} ".format(total=vehicle_count)), (393, 154),cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1) #a47
        #cv2.putText(frame,"- Perbandingan Kecepatan: " + str(direction_cache[0]), (393, 154), font, 0.4, (0,0, 0), 1,cv2.FONT_HERSHEY_COMPLEX_SMALL)
        cv2.putText(frame,"- Kecepatan (km/h): " + str(speed_cache[0]), (393, 170), font, 0.4, (0, 0, 0), 1,cv2.FONT_HERSHEY_COMPLEX_SMALL)
        #cv2.putText(frame,"-Color: " + "color", (14, 322), font, 0.4, (0,0, 0), 1,cv2.FONT_HERSHEY_COMPLEX_SMALL)
        #cv2.putText(frame,"- Vehicle Type: " + "size", (393, 184), font, 0.4, (0, 0, 0), 1,cv2.FONT_HERSHEY_COMPLEX_SMALL)
        cv2.putText(frame, ("- Jumlah Mobil: {total} ".format(total=car)), (393, 184), font, 0.4, (0, 0, 0), 1,cv2.FONT_HERSHEY_COMPLEX_SMALL)
        cv2.putText(frame, ("- Jumlah Motor: {total} ".format(total=motor)), (393, 200), font, 0.4, (0, 0, 0), 1,cv2.FONT_HERSHEY_COMPLEX_SMALL)


        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        cv2.imshow('vehicle detection',frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print('exit')
                
        return context
