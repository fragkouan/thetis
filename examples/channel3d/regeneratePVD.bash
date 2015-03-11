#!/bin/bash

end=1416
OUT=$1
python generatePVD.py -d $OUT -e $end -n Elevation2d
python generatePVD.py -d $OUT -e $end -n Elevation3d
python generatePVD.py -d $OUT -e $end -n Velocity2d
python generatePVD.py -d $OUT -e $end -n Velocity3d
python generatePVD.py -d $OUT -e $end -n VertVelo3d
python generatePVD.py -d $OUT -e $end -n Salinity3d
