"""Base classes for generic time series analysis.

The classes implemented here are meant to provide fairly basic objects for
managing time series data.  They should serve mainly as data containers, with
only minimal algorithmic functionality.

In the timeseries subpackage, there is a separate library of algorithms, and
the classes defined here mostly delegate any computational facilitites they may
have to that library.

Over time, it is OK to add increasingly functionally rich classes, but only
after their design is well proven in real-world use.

Authors
-------
- Ariel Rokem <arokem@berkeley.edu>, 
- Fernando Perez <Fernando.Perez@berkeley.edu>.
- Mike Trumpis <mtrumpis@gmail.com>
- Paul Ivanov <pivanov@berkeley.edu>
- Kilian Koepsell <kilian@berkeley.edu>
- Tim Blanche <tjb@berkeley.edu>
- Drew Fegen <dfegen@gmail.com> 

"""
#-----------------------------------------------------------------------------
# Public interface
#-----------------------------------------------------------------------------
__all__ = ['time_unit_conversion',
           'TimeSeriesInterface',
           'UniformTimeSeries',
           ]
#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

import warnings
import numpy as np
import scipy.signal as signal

# Our own
from nitime import descriptors as desc
from nitime import utils as tsu
from nitime import algorithms as tsa

reload(tsa)
reload(tsu)
#-----------------------------------------------------------------------------
# Module globals
#-----------------------------------------------------------------------------

# These are the valid names for time units, taken from the Numpy date/time
# types specification document.  They conform to SI nomenclature where
# applicable.

# Most uses of this are membership checks, so we make a set for fast
# validation.  But we create them first as a list so we can print an ordered
# and easy to read error message.

time_unit_conversion = {
                        'ps':1, #picosecond 
                        'ns':10**3,  # nanosecond
                        'us':10**6,  # microsecond
                        'ms':10**9,  # millisecond
                        's':10**12,   # second
                        None:10**12, #The default is seconds (when constructor
                                     #doesn't get any input, it defaults to
                                     #None)
                        'm':60*10**12,   # minute
                        'h':3600*10**12,   # hour
                        'D':24*3600*10**12,   # day
                        'W':7*24*3600*10**12,   # week #This is not an SI unit
                        }

#The basic resolution: 
base_unit = 'ps'


#-----------------------------------------------------------------------------
# Class declarations
#-----------------------------------------------------------------------------

##Time: 
class TimeInterface(object):
    """ The minimal object interface for time representations

    This should be thought of as an abstract base class. """

    time_unit = None
    
class TimeArray(np.ndarray,TimeInterface):
    """Base-class for time representations, implementing the TimeInterface"""  
    def __new__(cls, data, time_unit=None, copy=False):
        """XXX Write a doc-string - in particular, mention the the default
        time-units to be used are seconds (which is why it is set to None) """ 

        #Check that the time units provided are sensible: 
        if time_unit not in time_unit_conversion:
             raise ValueError('Invalid time unit %s, must be one of %s' %
                             (time_unit,time_unit_conversion.keys()))         

        conv_fac = time_unit_conversion[time_unit]

        # We can only honor the copy flag in a very narrow set of cases
        # if data is already an TimeArray or if data is an ndarray with
        # dtype=int64
        if copy==False and getattr(data, 'dtype', None) == np.int64:
            time = np.asarray(data)
        else:
            # XXX: do we mean isinstance(data,TimeInterface) - it could also be
            # NonUniformTime or UniformTime, it doesn't have to be an
            # TimeArray
            if isinstance(data, TimeArray):
                time = data.copy()
            else:
                data_arr = np.asarray(data)
                if issubclass(data_arr.dtype.type,np.integer):
                    #If this is an array of integers, cast to 64 bit integer
                    #and convert to the base_unit.
                    #XXX This will fail when even 64 bit is not large enough to
                    #avoid wrap-around (When you try to make more than 10**6
                    #seconds). XXX this should be mentioned in the docstring
                    time = data_arr.astype(np.int64)*conv_fac
                else:
                    #Otherwise: first convert, round and then cast to 64 
                    time=(data_arr*conv_fac).round().astype(np.int64)

        #Make sure you have an array on your hands (for example, if you input
        #an integer, you might have reverted to an integer when multiplying
        #with the conversion factor:            
        time = np.asarray(time).view(cls)

        if time_unit is None and isinstance(data, TimeArray):
            time_unit = data.time_unit

        if time_unit is None:
            time_unit = 's'

        time.time_unit = time_unit
        time._conversion_factor = conv_fac
        return time
    
    def __array_wrap__(self, out_arr, context=None):
        #When doing comparisons between TimeArrays, make sure that you 
        if out_arr.dtype==bool:
            return np.asarray(out_arr)
        else:
            return np.ndarray.__array_wrap__(self, out_arr, context)

    def __array_finalize__(self,obj):
        """XXX """
        #Make sure that the TimeArray has the time units set (and not equal to
        #None: 
        if not hasattr(self, 'time_unit') or self.time_unit is None:
            if hasattr(obj, 'time_unit'): # looks like view cast
                self.time_unit = obj.time_unit
            else:
                self.time_unit = 's'

        #Make sure that the conversion factor is set properly: 
        if not hasattr(self,'_conversion_factor'):
            if hasattr(obj,'_conversion_factor'):
                self._conversion_factor = obj._conversion_factor
            else:
                self._conversion_factor=time_unit_conversion[self.time_unit]

    def __repr__(self):
       """Pass it through the conversion factor"""

       #If the input is a single int/float (with no shape) return a 'scalar'
       #time-point: 
       if self.shape == ():
           return "%r %s"%(int(self)/float(self._conversion_factor),
                           self.time_unit)
       
       #Otherwise, return the TimeArray representation:
       else:
           return np.ndarray.__repr__(self/float(self._conversion_factor)
            )[:-1] + ", time_unit='%s')" % self.time_unit

    def __getitem__(self,key):
        # return scalar TimeArray in case key is integer
        if isinstance(key,int):
            return self[[key]].reshape(())
        elif isinstance(key,float):
            return self.at(key)
        else:
            return np.ndarray.__getitem__(self,key)

    def __setitem__(self,key,val):
        
    #look at the units - convert the values to what they need to be (in the
    #base_unit) and then delegate to the ndarray.__setitem__
    
       val = val * self._conversion_factor
       return np.ndarray.__setitem__(self,key,val)
    
    def index_at(self,t,tol=None):
        """ Find the integer indices that corresponds to the time t"""
        t_e = TimeArray(t,time_unit=self.time_unit)
        d = np.abs(self-t_e)
        if tol is None:
            idx=np.where(d==np.min(d))
        else:
            #tolerance is converted into a time-array, so that it does the
            #right thing:
            tol = TimeArray(tol,time_unit=self.time_unit)
            idx=np.where(d<=tol)            

        return idx

    def at(self,t,tol=None):
        """ Returns the values of the items at the """
        return self[self.index_at(t,tol=tol)]

    def convert_unit(self,time_unit):
        """Convert from one time unit to another in place"""
        #XXX Implement
        pass
     
class UniformTime(np.ndarray,TimeInterface):
    """ A representation of time sampled uniformly

    Parameters
    ----------
    
    length: int, the number of items in the time-array

    duration: float, the duration to be represented (given in the time-unit) of
    the array. If this item is an TimeArray, the units of the UniformTime
    array resulting will 'inherit' the units of the duration. Otherwise, the
    unit of the UniformTime will be set by that kwarg

    sampling_rate: float, the sampling rate (in 1/time-unit)

    sampling_interval: float, the inverse of the sampling_interval     

    t0: the value of the first time-point in the array (in time-unit)

    time_unit:

    copy: whether to make a copy of not. Needs to be set to False 

    
    

    XXX continue writing this
    """

    def __new__(cls,data=None,length=None,duration=None,sampling_rate=None,
                sampling_interval=None,t0=0,time_unit=None, copy=False):
        """Create a new UniformTime """

        #Sanity checks. There are different valid combinations of inputs
        tspec = tuple(x is not None for x in
                      [sampling_interval,sampling_rate,length,duration])

        #The valid configurations 
        valid_tspecs=[
            #interval,length:
            (True,False,True,False),
            #interval,duration:
            (True,False,False,True),
            #rate,length:
            (False,True,True,False),
            #rate, duration:
            (False,True,False,True),
            #length,duration:
            (False,False,True,True)
            ]

        if isinstance(data,UniformTime):
            #Assuming data was given, some other tspecs become valid:
            valid_w_data=[
                #nothing:
                (False,False,False,False),
                #interval:
                (True,False,False,False),
                #rate
                (False,True,False,False),
                #length:
                (False,False,True,False),
                #duration:
                (False,False,False,True)
                ]        

        if (tspec not in valid_tspecs and
            not(isinstance(data,UniformTime) and tspec in valid_w_data)):
            l = ['sampling_interval','sampling_rate','length','duration']
            args = [arg for t,arg in zip(tspec,l) if t]
            raise ValueError("Invalid time specification," +
            "You provided: %s see docstring." %(" ".join(args)))
            #XXX Needs more engineering in here in order to tell the user not
            #only what they provided, but also what more they should provide in
            #order for this to be valid 

        if isinstance(data,UniformTime):
            #Get attributes from the UniformTime object and transfer those over:
            if tspec==valid_w_data[0]:
                sampling_rate=data.sampling_rate
                duration = data.duration
            elif tspec==valid_w_data[1]:
                duration==data.duration
            elif tspec==valid_w_data[2]:
                if isinstance(sampling_rate,Frequency):
                    sampling_interval=sampling_rate.to_period()
                else:
                    sampling_interval = 1.0/sampling_rate
                duration=data.duration
            elif tspec==valid_w_data[3]:
                duration=length*data.sampling_interval
                sampling_rate=data.sampling_rate
            elif tspec==valid_w_data[4]:
                sampling_rate=data.sampling_rate
            if time_unit is None:
                #If the user didn't ask to change the time-unit, use the
                #time-unit from the object you got:
                time_unit = data.time_unit      
        # Check that the time units provided are sensible: 
        if time_unit not in time_unit_conversion:
            raise ValueError('Invalid time unit %s, must be one of %s' %
                         (time_unit,time_unit_conversion.keys()))         

        #Calculate the sampling_interval or sampling_rate:
        if sampling_interval is None:
            if isinstance(sampling_rate,Frequency):
                sampling_interval=sampling_rate.to_period()
            elif sampling_rate is None:
                sampling_interval = float(duration)/length
                sampling_rate = Frequency(1.0/sampling_interval,
                                             time_unit=time_unit)

            else:
                sampling_rate = Frequency(sampling_rate,time_unit='s')
                sampling_interval = sampling_rate.to_period()
        else:
            sampling_rate = Frequency(1.0/sampling_interval)

        #Calculate the duration, if that is not defined:
        if duration is None:
            duration=length*sampling_interval

        # Make sure you have a time unit:
        if time_unit is None:
            #If you gave us a duration with time_unit attached 
            if isinstance(duration,TimeArray):
                time_unit = duration.time_unit
            else:
                time_unit = 's'

        # 'cast' the time inputs as TimeArray
        duration=TimeArray(duration,time_unit=time_unit)
        #XXX If data is given - the t0 should be taken from there:
        t0=TimeArray(t0,time_unit=time_unit)
        sampling_interval=TimeArray(sampling_interval,time_unit=time_unit)

        #Check that the inputs are consistent, before making the array
        #itself:
        if duration<sampling_interval:
            raise ValueError('length/duration too short for the sampling_interval/sampling_rate')
        
        #in order for time[-1]-time[0]==duration to be true (which it should)
        #add the samling_interval to the stop value: 
        #time = np.arange(np.int64(t0),np.int64(t0+duration+sampling_interval),
        #                  np.int64(sampling_interval),dtype=np.int64)

        #But it's unclear whether that's really the behavior we want?
        time = np.arange(np.int64(t0),np.int64(t0+duration),
                         np.int64(sampling_interval),dtype=np.int64)

        time = np.asarray(time).view(cls)
        time.time_unit=time_unit
        time._conversion_factor=time_unit_conversion[time_unit]
        time.duration = duration
        time.sampling_rate=Frequency(sampling_rate)
        time.sampling_interval=sampling_interval
        time.t0 = t0
        
        return time

    def __array_wrap__(self, out_arr, context=None):
        #When doing comparisons between TimeArrays, make sure that you retun a
        #boolean array, not a time array: 
        if out_arr.dtype==bool:
            return np.asarray(out_arr)
        else:
            return np.ndarray.__array_wrap__(self, out_arr, context)

    def __array_finalize__(self,obj):
        """XXX """
        #Make sure that the UniformTime has the time units set (and not equal to
        #None): 
        if not hasattr(self, 'time_unit') or self.time_unit is None:
            if hasattr(obj, 'time_unit'): # looks like view cast
                self.time_unit = obj.time_unit
            else:
                self.time_unit = 's'

        #Make sure that the conversion factor is set properly: 
        if not hasattr(self,'_conversion_factor'):
            if hasattr(obj,'_conversion_factor'):
                self._conversion_factor = obj._conversion_factor
            else:
                self._conversion_factor=time_unit_conversion[self.time_unit]

    def __repr__(self):
       """Pass it through the conversion factor"""

       #If the input is a single int/float (with no shape) return a 'scalar'
       #time-point: 
       if self.shape == ():
           return "%r %s"%(int(self)/float(self._conversion_factor),
                           self.time_unit)
       
       #Otherwise, return the UniformTime representation:
       else:
           return np.ndarray.__repr__(self/float(self._conversion_factor)
            )[:-1] + ", time_unit='%s')" % self.time_unit

    def __getitem__(self,key):
        # return scalar TimeArray in case key is integer
        if isinstance(key,int):
            return self[[key]].reshape(())
        elif isinstance(key,float):
            return self.at(key)
        else:
            return np.ndarray.__getitem__(self,key)

    def __setitem__(self,key,val):
        
    #look at the units - convert the values to what they need to be (in the
    #base_unit) and then delegate to the ndarray.__setitem__
    
       val = val * self._conversion_factor
       return np.ndarray.__setitem__(self,key,val)


##Frequency:

class Frequency(float):
    """A class for representation of the frequency (in Hz) """

    def __new__(cls,f,time_unit='s'):
        """Initialize a frequency object """

        tuc = time_unit_conversion
        scale_factor = (float(tuc['s'])/tuc[time_unit])
        #If the input is a Frequency object, it is already in Hz: 
        if isinstance(f,Frequency)==False:
            #But otherwise convert to Hz:
            f = f*scale_factor

        freq = super(Frequency,cls).__new__(cls,f)
        freq._time_unit = time_unit

        return freq

    def __repr__(self):
        
        return str(self) + ' Hz'

    def to_period(self,time_unit=base_unit):
        """Convert the value of a frequency to the corresponding period
        (defaulting to a representation in the base_unit)

        """
        tuc = time_unit_conversion
        scale_factor = (float(tuc['s'])/tuc[time_unit])
        
        return np.int64((1/self)*scale_factor)
        
##Time-series: 
class TimeSeriesInterface(object):
    """The minimally agreed upon interface for all time series.

    This should be thought of as an abstract base class.
    """
    time = None
    data = None
    time_unit = None
    metadata = None
    

class TimeSeriesBase(object):
    """Base class for time series, implementing the TimeSeriesInterface."""

    def __init__(self,data,time_unit):
        """Common constructor shared by all TimeSeries classes."""
        # Check that sensible time units were given
        if time_unit not in time_unit_conversion:
            raise ValueError('Invalid time unit %s, must be one of %s' %
                             (time_unit,time_unit_conversion.keys()))
        
        #: the data is an arbitrary numpy array
        self.data = np.asarray(data)
        self.time_unit = time_unit

        # Every instance carries an empty metadata dict, which we promise never
        # to touch.  This reserves this name as a user area for extra
        # information without the danger of name clashes in the future.
        self.metadata = {}


    def __len__(self):
        """Return the length of the time series."""
        return self.data.shape[-1]


    def _validate_dimensionality(self):
        """Check that the data and time have the proper dimensions.
        """

        if self.time.ndim != 1:
            raise ValueError("time array must be one-dimensional")
        npoints = self.data.shape[-1]
        if npoints != len(self.time):
            raise ValueError("mismatch of time and data dimensions")

        
class UniformTimeSeries(TimeSeriesBase):
    """Represent data collected at uniform intervals.
    
    Examples 
    --------

    The minimal specication of data and sampling interval:

    >>> ts = UniformTimeSeries([1,2,3],sampling_interval=0.25)
    >>> ts.time
    UniformTime([ 0.  ,  0.25,  0.5 ], time_unit='s')
    >>> ts.t0
    0.0 s
    >>> ts.sampling_rate
    4.0 Hz

    Or data and sampling rate:
    >>> ts = UniformTimeSeries([1,2,3],sampling_rate=2)
    >>> ts.time
    UniformTime([ 0. ,  0.5,  1. ], time_unit='s')
    >>> ts.t0
    0.0 s
    >>> ts.sampling_interval
    0.5 s

    A time series where we specify the start time and sampling interval:
    >>> ts = UniformTimeSeries([1,2,3],t0=4.25,sampling_interval=0.5)
    >>> ts.data
    array([1, 2, 3])
    >>> ts.time
    UniformTime([ 4.25,  4.75,  5.25], time_unit='s')
    >>> ts.t0
    4.25 s
    >>> ts.sampling_interval
    0.5 s
    >>> ts.sampling_rate
    2.0 Hz

    >>> ts = UniformTimeSeries([1,2,3],t0=4.25,sampling_rate=2.0)
    >>> ts.data
    array([1, 2, 3])
    >>> ts.time
    UniformTime([ 4.25,  4.75,  5.25], time_unit='s')
    >>> ts.t0
    4.25 s
    >>> ts.sampl
    ts.sampling_interval  ts.sampling_rate      
    >>> ts.sampling_interval
    0.5 s
    >>> ts.sampling_rate
    2.0 Hz

    """

    @desc.setattr_on_read
    def time(self):
        """Construct time array for the time-series object. This holds a
    UniformTime object, with properties derived from the UniformTimeSeries
    object"""
        return UniformTime(length=self.__len__(),t0=self.t0,
                           sampling_interval=self.sampling_interval,
                           time_unit=self.time_unit)

    #XXX This should call the constructor in an appropriate way, when provided
    #with a UniformTime object and data, so that you don't need to deal with
    #the constructor itself:  
    @staticmethod
    def from_time_and_data():
        pass
    
    
    def __init__(self, data, t0=None, sampling_interval=None,
                 sampling_rate=None, duration=None, time=None, time_unit='s'):
        """Create a new UniformTimeSeries.

        This class assumes that data is uniformly sampled, but you can specify
        the sampling in one of three (mutually exclusive) ways:

        - sampling_interval [, t0]: data sampled starting at t0, equal
          intervals of sampling_interval.

        - sampling_rate [, t0]: data sampled starting at t0, equal intervals of
          width 1/sampling_rate.

        - time: a UniformTime object, in which case the UniformTimeSeries can
          'inherit' the properties of this object.  
        
        Parameters
        ----------
        data : array_like
          Data array, interpreted as having its last dimension being time.
        sampling_interval : float
          Interval between successive time points.
        sampling_rate : float
          Inverse of the interval between successive time points.
        t0 : float
          If you provide a sampling rate, you can optionally also provide a
          starting time.
        time
          Instead of sampling rate, you can explicitly provide an object of
        class UniformTime. Note that you can still also provide a different
        sampling_rate/sampling_interval/duration to take the place of the one
        in this object, but only as long as the changes are consistent with the
        length of the data. 
        
        time_unit :  string
          The unit of time.
        """

        #If a UniformTime object was provided as input: 
        if isinstance(time,UniformTime):
            c_fac = time._conversion_factor
            #If the user did not provide an alternative t0, get that from the
            #input: 
            if t0 is None:
                t0=time.t0
            #If the user did not provide an alternative sampling interval/rate:
            if sampling_interval is None and sampling_rate is None:
                sampling_interval = time.sampling_interval
                sampling_rate = time.sampling_rate
            #The duration can be read either from the length of the data, or
            #from the duration specified by the time-series: 
            if duration is None:
                duration=time.duration
                length = time.shape[-1]
                #If changing the duration requires a change to the
                #sampling_rate, make sure that this was explicitely required by
                #the user - if the user did not explicitely set the
                #sampling_rate, or it is inconsistent, throw an error: 
                if (length != len(data) and
                    sampling_rate != float(len(data)*c_fac)/time.duration):
                    e_s = "Length of the data (%s) " %str(len(data))  
                    e_s += "specified sampling_rate (%s) " %str(sampling_rate)
                    e_s +="do not match."
                    raise ValueError(e_s)
            #If user does not provide a     
            if time_unit is None:
                time_unit = time.time_unit

        else:    
            ##If the input was not a UniformTime, we need to check that there
            ##is enough information in the input to generate the UniformTime
            ##array.

            #There are different valid combinations of inputs
            tspec = tuple(x is not None for x in
                      [sampling_interval,sampling_rate,duration])

            #The valid configurations 
            valid_tspecs=[
                      #interval,length:
                      (True,False,False),
                      #interval,duration:
                      (True,False,True),
                      #rate,length:
                      (False,True,False),
                      #rate, duration:
                      (False,True,True),
                      #length,duration:
                      (False,False,True)
                      ]

            if tspec not in valid_tspecs:
                raise ValueError("Invalid time specification, see docstring.")

        
        # Call the common constructor to get the real object initialized
        TimeSeriesBase.__init__(self,data,time_unit)
        
        #Calculate the sampling_interval or sampling_rate from each other and
        #assign t0, if it is not already assigned:
        if sampling_interval is None:
            if isinstance(sampling_rate,Frequency):
                sampling_interval=sampling_rate.to_period()
            elif sampling_rate is None:
                sampling_interval = float(duration)/self.__len__()
                sampling_rate = Frequency(1.0/sampling_interval,
                                             time_unit=time_unit)

            else:
                sampling_rate = Frequency(sampling_rate,time_unit='s')
                sampling_interval = sampling_rate.to_period()
        elif sampling_rate is None:
           sampling_rate = Frequency(1.0/sampling_interval,time_unit=time_unit)

        #Calculate the duration, if that is not defined:
        if duration is None:
            duration=self.__len__()*sampling_interval

        if t0 is None:
           t0=0   
    
        self.time_unit = time_unit
        self.sampling_interval = TimeArray(sampling_interval,
                                           time_unit=self.time_unit) 
        self.t0 = TimeArray(t0,time_unit=self.time_unit)
        self.sampling_rate = sampling_rate
        self.duration = TimeArray(duration,time_unit=self.time_unit)

class NonUniformTimeSeries(TimeSeriesBase):
    """Represent data collected at arbitrary time points.

    This class combines a one dimensional array of time values (assumed, but
    not verified, to be monotonically increasing) with an n-dimensional array
    of data values.

    Examples
    --------
    >>> t = np.array([0.3, 0.5, 1, 1.9])
    >>> y = np.array([4.7, 8.4, 9.1, 10.4])
    >>> uts = NonUniformTimeSeries(t,y)
    >>> uts.time
    array([  4.7,   8.4,   9.1,  10.4])
    >>> uts.data
    array([ 0.3,  0.5,  1. ,  1.9])
    >>> uts.time_unit
    's'
    """

    def __init__(self,data,time,time_unit='s'):
        """Construct a new NonUniformTimeSeries from data and time.

        Parameters
        ----------
        data : ndarray
          An n-dimensional dataset whose last axis runs along the time
          direction.
        time : 1-d array
          A sorted array of time values, with as many points as the last
          dimension of the dataset.
        time_unit :  string
          The unit of time.
        """
        # Call the common constructor to get the real object initialized
        TimeSeriesBase.__init__(self,data,time_unit)

        self.time = np.asarray(time)


def time_series_from_file(analyze_file,coords,normalize=False,detrend=False,
                           average=False,f_c=0.01,TR=None):
    """ Make a time series from a Analyze file, provided coordinates into the
            file 

    Parameters
    ----------

    analyze_file: string.

           The full path to the file from which the time-series is extracted 
     
    coords: ndarray or list of ndarrays
           x,y,z (slice,inplane,inplane) coordinates of the ROI from which the
           time-series is to be derived. If the list has more than one such
           array, the t-series will have more than one row in the data, as many
           as there are coordinates in the total list. Averaging is done on
           each item in the list separately, such that if several ROIs are
           entered, averaging will be done on each one separately and the
           result will be a time-series with as many rows of data as different
           ROIs in the input 

    detrend: bool, optional
           whether to detrend the time-series . For now, we do box-car
           detrending, but in the future we will do real high-pass filtering

    normalize: bool, optional
           whether to convert the time-series values into % signal change (on a
           voxel-by-voxel level)

    average: bool, optional
           whether to average the time-series across the voxels in the ROI. In
           which case, self.data will be 1-d

    f_c: float, optional
        cut-off frequency for detrending

    TR: float, optional
        TR, if different from the one which can be extracted from the nifti
        file header

    Returns
    -------

    time-series object

        """
    try:
        from nipy.io.files import load
    except ImportError: 
        print "nipy not available"
    
    im = load(analyze_file)
    data = np.asarray(im)
    #Per default read TR from file:
    if TR is None:
        TR = im.header.get_zooms()[-1]/1000.0 #in msec?
        
    #If we got a list of coord arrays, we're happy. Otherwise, we want to force
    #our input to be a list:
    try:
        coords.shape #If it is an array, it has a shape, otherwise, we 
        #assume it's a list. If it's an array, we want to
        #make it into a list:
        coords = [coords]
    except: #If it's a list already, we don't need to do anything:
        pass

    #Make a list the size of the coords-list, with place-holder 0's
    data_out = list([0]) * len(coords)

    for c in xrange(len(coords)): 
        data_out[c] = data[coords[c][0],coords[c][1],coords[c][2],:]
        
        if normalize:
            data_out[c] = tsu.percent_change(data_out[c])

        #Currently uses mrVista style box-car detrending, will eventually be
        #replaced by a filter:
    
        if detrend:
            from nitime import vista_utils as tsv
            data_out[c] = tsv.detrend_tseries(data_out[c],TR,f_c)
            
        if average:
            data_out[c] = np.mean(data_out[c],0)

    #Convert this into the array with which the time-series object is
    #initialized:
    data_out = np.array(data_out).squeeze()
        
    tseries = UniformTimeSeries(data_out,sampling_interval=TR)

    return tseries


def nifti_from_time_series(volume,coords,time_series,nifti_path):
    """Makes a Nifti file out of a time_series object

    Parameters
    ----------

    volume: list (3-d, or 4-d)
        The total size of the nifti image to be created

    coords: 3*n_coords array
        The coords into which the time_series will be inserted. These need to
        be given in the order in which the time_series is organized

    time_series: a time-series object
       The time-series to be inserted into the file

    nifti_path: the full path to the file name which will be created
    
       """
    # XXX Implement! 
    raise NotImplementedError
    
def concatenate_uniform_time_series(time_series_list):
    """Concatenates a list of time-series objects in time, according to their
    order in the input list.

    This one requires that all the time-series in the list have the same
    sampling rate and that all the data have the same number of items in all
    dimensions, except the time dimension"""

    total_len = 0
    for i in xrange(len(time_series_list)):
        total_len += time_series_list[i].data.shape[-1]

    #The data in the output object has the size of the input time-series,
    #except in the last dimension (time), where it has the sum of all the
    #lengths of the time-series:
    
    data_out = np.empty(time_series_list[0].data.shape[0:-1]
                        + (total_len,)) #this variable is an int, so needs to
                                        #be cast into a tuple, so that it can
                                        #be used to initialize the empty variable
    
    idx_start = 0
    for i in xrange(len(time_series_list)):
        idx_end = idx_start+time_series_list[i].data.shape[-1]
        data_out[...,idx_start:idx_end] = time_series_list[i].data
        idx_start = idx_end


    tseries = UniformTimeSeries(data_out,
                    sampling_interval=time_series_list[0].sampling_interval)

    return tseries

    
def concatenate_time_series(time_series_list):
    """Concatenates a list of time series objects in time, according to their
    order in the input list.

    This one doesn't require that the time-series all have the same sampling
    rate. Requires that the data all have the same number of rows""" 

    # XXX Implement! Probably as generalization of above
    # (concatenate_uniform_time_series)
    raise NotImplementedError


#-----------------------------------------------------------------------------
# Analyzer classes
#-----------------------------------------------------------------------------

"""These classes are used in order to bridge between the time series objects
and the algorithms provided in the algorithms library. The different analysis
objects contain methods in order to call a family of algorithms and caches
quantities related to this particular family. In general, the objects
initialize on a time series object and analytical results are then derived from
the combination of that time-series and the algorithms  """


##Spectral estimation: 
class SpectralAnalyzer(desc.ResetMixin):

    """ Analyzer object for spectral analysis """
    def __init__(self,time_series,method=None):
        self.data = time_series.data
        self.sampling_rate = time_series.sampling_rate
        self.method=method
        
        if self.method is None:
            self.method = {}

    @desc.setattr_on_read
    def spectrum_fourier(self):
        """ Simply the non-normalized Fourier transform for a real signal"""

        fft = np.fft.fft
        f = tsu.get_freqs(self.sampling_rate,self.data.shape[-1])
        spectrum_fourier = fft(self.data)[...,:f.shape[0]]
        return f,spectrum_fourier 
        
    @desc.setattr_on_read
    def spectrum_mlab(self):
        """The spectrum and cross-spectra, computed using mlab csd """

        self.mlab_method = self.method
        self.mlab_method['this_method'] = 'mlab'
        self.mlab_method['Fs'] = self.sampling_rate
        f,spectrum_mlab = tsa.get_spectra(self.data,method=self.mlab_method)

        return f,spectrum_mlab
    
    @desc.setattr_on_read
    def spectrum_multi_taper(self):
        """The spectrum and cross-spectra, computed using multi-tapered csd """

        self.multi_taper_method = np.copy(self.method)
        self.multi_taper_method['this_method'] = 'multi_taper_csd'
        self.multi_taper_method['Fs'] = self.sampling_rate
        f,spectrum_multi_taper = tsa.get_spectra(self.data,
                                               method=self.multi_taper_method)
        return f,spectrum_multi_taper
    
    
##Bivariate methods:  
class CoherenceAnalyzer(desc.ResetMixin):
    """ Analyzer object for coherence/y analysis"""
    
    def __init__(self,time_series,method=None):
        #Initialize variables from the time series
        self.data = time_series.data
        self.sampling_rate = time_series.sampling_rate
        self.time = time_series.time
        
        #Set the variables for spectral estimation (can also be entered by user):
        if method is None:
            self.method = {'this_method':'mlab'}

        else:
            self.method = method
            
        self.method['Fs'] = self.method.get('Fs',self.sampling_rate)

    @desc.setattr_on_read
    def spectrum(self):
        f,spectrum = tsa.get_spectra(self.data,method=self.method)
        return spectrum

    @desc.setattr_on_read
    def frequencies(self):
        f,spectrum = tsa.get_spectra(self.data,method=self.method)
        return f
    
    @desc.setattr_on_read
    def coherence(self):

        tseries_length = self.data.shape[0]
        spectrum_length = self.spectrum.shape[-1]
        coherence=np.zeros((tseries_length,
                            tseries_length,
                            spectrum_length))
    
        for i in xrange(tseries_length): 
            for j in xrange(i,tseries_length):
                coherence[i][j] = tsa.coherence_calculate(self.spectrum[i][j],
                                                      self.spectrum[i][i],
                                                      self.spectrum[j][j])  

        idx = tsu.tril_indices(tseries_length,-1)
        coherence[idx[0],idx[1],...] = coherence[idx[1],idx[0],...].conj()
        
        return coherence

    @desc.setattr_on_read
    def coherency(self):

        tseries_length = self.data.shape[0]
        spectrum_length = self.spectrum.shape[-1]

        coherency=np.zeros((tseries_length,
                            tseries_length,
                            spectrum_length),dtype=complex)
    
        for i in xrange(tseries_length): 
            for j in xrange(i,tseries_length):
                coherency[i][j] = tsa.coherency_calculate(self.spectrum[i][j],
                                                      self.spectrum[i][i],
                                                      self.spectrum[j][j])  

        idx = tsu.tril_indices(tseries_length,-1)
        coherency[idx[0],idx[1],...] = coherency[idx[1],idx[0],...].conj()
        
        return coherency
    
    @desc.setattr_on_read
    def phase(self):
        """ The frequency-dependent phase relationship between all the pairwise
        combinations of time-series in the data"""
        tseries_length = self.data.shape[0]
        spectrum_length = self.spectrum.shape[-1]

        phase = np.zeros((tseries_length,
                            tseries_length,
                            spectrum_length))

        for i in xrange(tseries_length): 
            for j in xrange(i,tseries_length):
                phase[i][j] = tsa.coherency_phase_spectrum_calculate\
                        (self.spectrum[i][j])

                phase[j][i] = tsa.coherency_phase_spectrum_calculate\
                        (self.spectrum[i][j].conjugate())
        return phase
    
    @desc.setattr_on_read
    def delay(self):
        """ The delay in seconds between the two time series """
        p_shape = self.phase.shape[:-1]
        delay = np.zeros(self.phase.shape)
        for i in xrange(p_shape[0]):
            for j in xrange(p_shape[1]):
                #Calculate the delay, unwrapping the phases:
                this_phase = self.phase[i,j]
                this_phase = tsu.unwrap_phases(this_phase)
                delay[i,j] = this_phase / (2*np.pi*self.frequencies)
                
        return delay
    
    @desc.setattr_on_read
    def coherence_partial(self):
        """The partial coherence between data[i] and data[j], given data[k], as
        a function of frequency band"""

        tseries_length = self.data.shape[0]
        spectrum_length = self.spectrum.shape[-1]

        p_coherence=np.zeros((tseries_length,
                              tseries_length,
                              tseries_length,
                              spectrum_length),dtype=complex)
    
        for i in xrange(tseries_length): 
            for j in xrange(tseries_length):
                for k in xrange(t_series_length):
                    p_coherence[i][j][k]=tsa.coherence_partial_calculate(
                        self.spectrum[i][j],
                        self.spectrum[i][i],
                        self.spectrum[j][j],
                        self.spectrum[i][k],
                        self.spectrum[j][k],
                        self.spectrum[k][k])  

        
        return p_coherence        
        
class SparseCoherenceAnalyzer(desc.ResetMixin):
    """This analyzer is intended for analysis of large sets of data, in which
    possibly only a subset of combinations of time-series needs to be compared.
    The constructor for this class receives as input not only a time-series
    object, but also a list of tuples with index combinations (i,j) for the
    combinations. Importantly, this class implements only the mlab csd function
    and cannot use other methods of spectral estimation""" 

    def __init__(self,time_series,ij,method=None,lb=0,ub=None,
                 prefer_speed_over_memory=False,
                 scale_by_freq=True):
        """The constructor for the SparseCoherenceAnalyzer

        Parameters
        ----------

        time_series: a time-series object
    
        ij: a list of tuples, each containing a pair of indices.

           The resulting cache will contain the fft of time-series in the rows
           indexed by the unique elements of the union of i and j
    
        lb,ub: float,optional, default: lb=0, ub=None (max frequency)

            define a frequency band of interest

        prefer_speed_over_memory: Boolean, optional, default=False

            Does exactly what the name implies. If you have enough memory

        method: optional, dict

         The method for spectral estimation (see `func`:algorithms.get_spectra:)

        """ 
        #Initialize variables from the time series
        self.data = time_series.data
        self.sampling_rate = time_series.sampling_rate
        self.ij = ij
        #Set the variables for spectral estimation (can also be entered by user):
        if method is None:
            self.method = {'this_method':'mlab'}

        else:
            self.method = method

        if self.method['this_method']!='mlab':
            raise ValueError("For SparseCoherenceAnalyzer, spectral estimation"
            "method must be mlab")
            
        self.method['Fs'] = self.method.get('Fs',self.sampling_rate)

        #Additional parameters for the coherency estimation: 
        self.lb = lb
        self.ub = ub
        self.prefer_speed_over_memory = prefer_speed_over_memory
        self.scale_by_freq = scale_by_freq
        
    @desc.setattr_on_read
    def cache(self):
        """Caches the fft windows required by the other methods of the
        SparseCoherenceAnalyzer. Calculate only once and reuse
        """
        f,cache = tsa.cache_fft(self.data,self.ij,
                          lb=self.lb,ub=self.ub,
                          method=self.method,
                          prefer_speed_over_memory=self.prefer_speed_over_memory,
                          scale_by_freq=self.scale_by_freq)

        return cache
    
    @desc.setattr_on_read
    def coherency(self):
        coherency = tsa.cache_to_coherency(self.cache,self.ij)

        return coherency
    
    @desc.setattr_on_read
    def spectrum(self):
        """get the spectrum for the collection of time-series in this analyzer
        """ 
        spectrum = tsa.cache_to_psd(self.cache,self.ij)

        return spectrum
    
    @desc.setattr_on_read
    def phases(self):
        """The frequency-band dependent phases of the spectra of the
           time-series i,j in the analyzer"""
        
        phase= tsa.cache_to_phase(self.cache,self.ij)

        return phase

    @desc.setattr_on_read
    def frequencies(self):
        """Get the central frequencies for the frequency bands, given the
           method of estimating the spectrum """

        NFFT = self.method.get('NFFT',64)
        Fs = self.method.get('Fs')
        freqs = tsu.get_freqs(Fs,NFFT)
        lb_idx,ub_idx = tsu.get_bounds(freqs,self.lb,self.ub)
        
        return freqs[lb_idx:ub_idx]
        
class CorrelationAnalyzer(desc.ResetMixin):
    """Analyzer object for correlation analysis. Has the same API as the
    CoherenceAnalyzer"""

    def __init__(self,time_series):
        #Initialize data from the time series
        self.data = time_series.data
        self.sampling_interval=time_series.sampling_interval

    @desc.setattr_on_read
    def correlation(self):
        """The correlation coefficient between every pairwise combination of
        time-series contained in the object""" 

        return np.corrcoef(self.data)  

    @desc.setattr_on_read
    def xcorr(self):
        """The cross-correlation between every pairwise combination time-series
        in the object. Uses np.correlation('full').

        Returns
        -------

        UniformTimeSeries: the time-dependent cross-correlation, with zero-lag
        at time=0"""
        tseries_length = self.data.shape[0]
        t_points = self.data.shape[-1]
        xcorr = np.zeros((tseries_length,
                          tseries_length,
                          t_points*2-1))
         
        for i in xrange(tseries_length): 
            for j in xrange(i,tseries_length):
                xcorr[i][j] = tsu.xcorr(self.data[i],self.data[j])

        idx = tsu.tril_indices(tseries_length,-1)
        xcorr[idx[0],idx[1],...] = xcorr[idx[1],idx[0],...]

        return UniformTimeSeries(xcorr,sampling_interval=self.sampling_interval,
                                 t0=-self.sampling_interval*t_points+1)
    @desc.setattr_on_read
    def xcorr_norm(self):
        """The cross-correlation between every pairwise combination time-series
        in the object, where the zero lag correlation is normalized to be equal
        to the correlation coefficient between the time-series

        Returns
        -------

        UniformTimeSeries: the time-dependent cross-correlation, with zero-lag
        at time=0"""

        tseries_length = self.data.shape[0]
        t_points = self.data.shape[-1]
        xcorr = np.zeros((tseries_length,
                          tseries_length,
                          t_points*2-1))
         
        for i in xrange(tseries_length): 
            for j in xrange(i,tseries_length):
                xcorr[i,j] = tsu.xcorr(self.data[i],self.data[j])
                xcorr[i,j] /= (xcorr[i,j,t_points])
                xcorr[i,j] *= self.correlation[i,j]

        idx = tsu.tril_indices(tseries_length,-1)
        xcorr[idx[0],idx[1],...] = xcorr[idx[1],idx[0],...]

        return UniformTimeSeries(xcorr,sampling_interval=self.sampling_interval,
                                 t0=-self.sampling_interval*t_points)
    
##Event-related analysis:
class EventRelatedAnalyzer(desc.ResetMixin): 
    """Analyzer object for reverse-correlation/event-related analysis.

    XXX Repeated use of the term the fmri specific term 'hrf' should be removed.

    """    

    def __init__(self,time_series,events_time_series,len_hrf,zscore=False,
                 correct_baseline=False,offset=0):
        """
        Parameters
        ----------
        time_series: a time-series object
           A time-series with data on which the event-related analysis proceeds
        
        events_time_series: a time_series object

        The events which occured in tandem with the time-series in the
        EventRelatedAnalyzer. This object's data has to have the same
        dimensions as the data in the EventRelatedAnalyzer object. In each
        sample in the time-series, there is an integer, which denotes the kind
        of event which occured at that time. In time-bins in which
        no event occured, a 0 should be entered. The data in this time series
        object needs to have the same dimensionality as the data in the data
        time-series 

        len_hrf: int
        
        The expected length of the HRF (in the same time-units as
        the events are represented (presumably TR). The size of the block
        dedicated in the fir_matrix to each type of event

        zscore: a flag to return the result in zscore (where relevant)

        correct_baseline: a flag to correct the baseline according to the first
        point in the event-triggered average (where possible)
        
        """ 
        #XXX enable the possibility that the event_time_series only has one
        #dimension, corresponding to time and then all channels have the same
        #series of events (and there is no need to loop over all channels?)
        #XXX Change so that the offset and length of the eta can be given in
        #units of time 

        #Make sure that the offset and the len_hrf values can be used, by
        #padding with zeros before and after:

        s = time_series.data.shape
        zeros_before = np.zeros((s[:-1]+ (abs(offset),)))
        zeros_after = np.zeros((s[:-1]+(abs(len_hrf),)))
        time_series_data = np.hstack([zeros_before,time_series.data,
                                      zeros_after])
        events_data = np.hstack([zeros_before,events_time_series.data,
                                 zeros_after])
        
        #If the events and the time_series have more than 1-d, the analysis can
        #traverse their first dimension
        if events_time_series.data.ndim-1>0:
            self._len_h = events_time_series.data.shape[0]
            self.events = events_data
            self.data = time_series_data
        #Otherwise, in order to extract the array from the first dimension, we
        #wrap it in a list
        
        else:
            self._len_h = 1
            self.events = [events_data]
            self.data = [time_series_data]


        self.sampling_rate = time_series.sampling_rate
        self.sampling_interval = time_series.sampling_interval
        self.len_hrf=int(len_hrf)
        self._zscore=zscore
        self._correct_baseline=correct_baseline
        self._offset=offset
        self.time_unit = time_series.time_unit
        
    @desc.setattr_on_read
    def FIR(self):
        """Calculate the FIR event-related estimated of the HRFs for different
        kinds of events

       Returns
        -------

        A time-series object, shape[:-2] are dimensions corresponding to the to
        shape[:-2] of the EventRelatedAnalyzer data, shape[-2] corresponds to
        the different kinds of events used (ordered according to the sorted
        order of the unique components in the events time-series). shape[-1]
        corresponds to time, and has length = len_hrf

        XXX code needs to be changed to use flattening (see 'eta' below)
        
        """
            
        #Make a list to put the outputs in:
        h = [0] * self._len_h

        for i in xrange(self._len_h):
            #XXX Check that the offset makes sense (there can't be an event
            #happening within one offset duration of the beginning of the
            #time-series:

            #Get the design matrix (roll by the offset, in order to get the
            #right thing): 

            roll_events = np.roll(self.events[i],self._offset)
            design = tsu.fir_design_matrix(roll_events,self.len_hrf+
                                           abs(self._offset))
            #Compute the fir estimate, in linear form: 
            this_h = tsa.fir(self.data[i],design)
            #Reshape the linear fir estimate into a event_types*hrf_len array
            u = np.unique(self.events[i])
            event_types = u[np.unique(self.events[i])!=0]
            h[i] =np.reshape(this_h,(event_types.shape[0],self.len_hrf+
                                     abs(self._offset)))

        h = np.array(h).squeeze()

        return UniformTimeSeries(data=h,sampling_rate=self.sampling_rate,
                                 t0=-1*self.len_hrf*self.sampling_interval,
                                 time_unit=self.time_unit)

    
    @desc.setattr_on_read
    def FIR_estimate(self):
        """Calculate back the LTI estimate of the time-series, from FIR"""
        raise NotImplementedError
    
    @desc.setattr_on_read
    def xcorr_eta(self):
        """Compute the normalized cross-correlation estimate of the HRFs for
        different kinds of events
        
        Returns
        -------

        A time-series object, shape[:-2] are dimensions corresponding to the to
        shape[:-2] of the EventRelatedAnalyzer data, shape[-2] corresponds to
        the different kinds of events used (ordered according to the sorted
        order of the unique components in the events time-series). shape[-1]
        corresponds to time, and has length = len_hrf*2 (xcorr looks both back
        and forward for this length)


        XXX code needs to be changed to use flattening (see 'eta' below)
        """
        #Make a list to put the outputs in:
        h = [0] * self._len_h

        for i in xrange(self._len_h):
            data = self.data[i]
            u = np.unique(self.events[i])
            event_types = u[np.unique(self.events[i])!=0]
            h[i] = np.empty((event_types.shape[0],self.len_hrf*2),dtype=complex)
            for e_idx in xrange(event_types.shape[0]):
                this_e = (self.events[i]==event_types[e_idx]) * 1.0
                if self._zscore:
                    this_h = tsa.event_related_zscored(data,
                                            this_e,
                                            self.len_hrf,
                                            self.len_hrf
                                            )
                else:
                    this_h = tsa.event_related(data,
                                            this_e,
                                            self.len_hrf,
                                            self.len_hrf
                                            )
                    
                h[i][e_idx] = this_h
                
        h = np.array(h).squeeze()

        ## t0 for the object returned here needs to be the central time, not the
        ## first time point, because the functions 'look' back and forth for
        ## len_hrf bins

        return UniformTimeSeries(data=h,
                                 sampling_rate=self.sampling_rate,
                                 t0 = -1*self.len_hrf*self.sampling_interval,
                                 time_unit=self.time_unit)

    @desc.setattr_on_read
    def eta(self):
        """The event-triggered average activity """
        #Make a list fo the output 
        h = [0] * self._len_h

        for i in xrange(self._len_h):
            data = self.data[i]
            u = np.unique(self.events[i])
            event_types = u[np.unique(self.events[i])!=0]
            h[i] = np.empty((event_types.shape[0],self.len_hrf),dtype=complex)
            for e_idx in xrange(event_types.shape[0]):
                idx = np.where(self.events[i]==event_types[e_idx])
                idx_w_len = np.array([idx[0]+count+self._offset for count
                                      in range(self.len_hrf)])
                event_trig = data[idx_w_len]
                #Correct baseline by removing the first point in the series for
                #each channel:
                if self._correct_baseline:
                    event_trig -= event_trig[0]
                    
                h[i][e_idx] = np.mean(event_trig,-1)
                
        h = np.array(h).squeeze()

#If the events were the same for all the channels, maybe you can take an
#        alternative approach?

#        d_flat = np.ravel(self.data)
#        e_flat = np.ravel(self.events)
#        u = np.unique(e_flat)
#        event_types = u[np.unique(self.events[i])!=0]
#        for e in event_types: 
#            idx = np.where(e_flat==e)
#            idx_new = np.array([idx[0]+i for i in range(self.len_hrf)])

        return UniformTimeSeries(data=h,
                                 sampling_rate=self.sampling_rate,
                                 t0=self._offset*self.sampling_interval,
                                 time_unit=self.time_unit)
    
        
class HilbertAnalyzer(desc.ResetMixin):

    """Analyzer class for extracting the Hilbert transform """ 

    def __init__(self,time_series,lb=0,ub=None):
        """Constructor function for the Hilbert analyzer class.

        Parameters
        ----------
        
        lb,ub: the upper and lower bounds of the frequency range for which the
        transform is done, where filtering is done using a simple curtailment
        of the Fourier domain 

        """
    
        data_in = time_series.data 

        self.sampling_rate = time_series.sampling_rate
        freqs = tsu.get_freqs(self.sampling_rate,data_in.shape[-1])

        if ub is None:
            ub = freqs[-1]
        
        power = np.fft.fft(data_in)
        idx_0 = np.hstack([np.where(freqs<lb)[0],np.where(freqs>ub)[0]])
        power[...,idx_0] = 0
        power[...,-1*idx_0] = 0 #Take care of the negative frequencies
        data_out = np.fft.ifft(power)

        self.data = np.real(data_out) #In order to make sure that you are not
                                      #left with float-precision residual
                                      #complex parts
                                      
    @desc.setattr_on_read
    def _analytic(self):
        return UniformTimeSeries(data=signal.hilbert(self.data),
                                 sampling_rate=self.sampling_rate)
        
    @desc.setattr_on_read
    def magnitude(self):
        return UniformTimeSeries(data=np.abs(self._analytic.data),
                                 sampling_rate=self.sampling_rate)
                                 
    @desc.setattr_on_read
    def phase(self):
        return UniformTimeSeries(data=np.angle(self._analytic.data),
                                 sampling_rate=self.sampling_rate)

    @desc.setattr_on_read
    def real(self):
        return UniformTimeSeries(data=np.real(self._analytic.data),
                                 sampling_rate=self.sampling_rate)
    


class FilterAnalyzer(desc.ResetMixin):

    """ A class for performing filtering operations on time-series and
    producing the filtered versions of the time-series"""

    
    def __init__(self,time_series,lb=0,ub=None):
        self.data = time_series.data 
        self.sampling_rate = time_series.sampling_rate
        self.freqs = tsu.get_freqs(self.sampling_rate,self.data.shape[-1])
        self.ub=ub
        self.lb=lb
        self.time_unit=time_series.time_unit

        
    @desc.setattr_on_read
    def filtered_fourier(self):

        """Filter the time-series by passing it to the Fourier domain and null
        out the frequency bands outside of the range [lb,ub] """
        
        if self.ub is None:
            self.ub = self.freqs[-1]
        
        power = np.fft.fft(self.data)
        idx_0 = np.hstack([np.where(self.freqs<self.lb)[0],
                           np.where(self.freqs>self.ub)[0]])
        
        power[...,idx_0] = 0
        #power[...,-1*idx_0] = 0 #Take care of the negative frequencies
        data_out = np.fft.ifft(power)

        data_out = np.real(data_out) #In order to make sure that you are not
                                      #left with float-precision residual
                                      #complex parts

        return UniformTimeSeries(data=data_out,
                                 sampling_rate=self.sampling_rate,
                                 time_unit=self.time_unit)
