'''
How to solve the HeNeAr line identify problem for real.

Using inspiration from astrometry.net and geometric hash tables

Goal: clumsy, slow, effective
'''


import pydis
from astropy.io import fits
import numpy as np
import os
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt



def _MakeTris(linewave0):
    '''

    :param linewave0:
    :return:
    '''
    linewave = linewave0.copy()
    linewave.sort()

    ntri = len(linewave)-2
    for k in range(ntri):
        # the 3 lines
        l1,l2,l3 = linewave[k:k+3]
        # the 3 "sides", ratios of the line separations
        s1 = abs( (l1-l3) / (l1-l2) )
        s2 = abs( (l1-l2) / (l2-l3) )
        s3 = abs( (l1-l3) / (l2-l3) )

        sides = np.array([s1,s2,s3])
        lines = np.array([l1,l2,l3])
        ss = np.argsort(sides)

        if (k==0):
            side_out = sides[ss]
            line_out = lines[ss]
        else:
            side_out = np.vstack((side_out, sides[ss]))
            line_out = np.vstack((line_out, lines[ss]))

    return side_out, line_out


def _BuildLineDict(linelist='apohenear.dat'):
    '''
    Build the dictionary (hash table) of lines from the master file.

    Goal is to do this once, store it in some hard file form for users.
    Users then would only re-run this function if linelist changed, say if
    a different set of lamps were used.
    '''

    dir = os.path.dirname(os.path.realpath(__file__))+ '/resources/linelists/'

    linewave = np.loadtxt(dir + linelist, dtype='float',
                           skiprows=1, usecols=(0,), unpack=True)

    # sort the lines, just in case the file is not sorted
    linewave.sort()

    sides, lines = _MakeTris(linewave)

    # now, how to save this dict? or should we just return it?
    return sides, lines


def autoHeNeAr(calimage, trim=True, maxdist=0.5, linelist='apohenear.dat', display=False):
    '''
    (REWORD later)
    Find emission lines, match triangles to dictionary (hash table),
    filter out junk, check wavelength order, assign wavelengths!

    Parameters
    ----------
    calimage : str
        the calibration (HeNeAr) image file name you want to solve

    '''

    # !!! this should be changed to pydis.OpenImg ?
    hdu = fits.open(calimage)
    if trim is False:
        img = hdu[0].data
    if trim is True:
        datasec = hdu[0].header['DATASEC'][1:-1].replace(':',',').split(',')
        d = map(float, datasec)
        img = hdu[0].data[d[2]-1:d[3],d[0]-1:d[1]]

    # this approach will be very DIS specific
    disp_approx = hdu[0].header['DISPDW']
    wcen_approx = hdu[0].header['DISPWC']

    # the red chip wavelength is backwards (DIS specific)
    clr = hdu[0].header['DETECTOR']
    if (clr.lower()=='red'):
        sign = -1.0
    else:
        sign = 1.0
    hdu.close(closed=True)

    # take a slice thru the data (+/- 10 pixels) in center row of chip
    slice = img[img.shape[0]/2-10:img.shape[0]/2+10,:].sum(axis=0)

    # use the header info to do rough solution (linear guess)
    wtemp = (np.arange(len(slice))-len(slice)/2) * disp_approx * sign + wcen_approx

    # the flux threshold to select peaks at
    flux_thresh = np.percentile(slice, 90)

    # find flux above threshold
    high = np.where( (slice >= flux_thresh) )
    # find  individual peaks (separated by > 1 pixel)
    pk = high[0][ ( (high[0][1:]-high[0][:-1]) > 1 ) ]
    # the number of pixels around the "peak" to fit over
    pwidth = 10
    # offset from start/end of array by at least same # of pixels
    pk = pk[pk > pwidth]
    pk = pk[pk < (len(slice)-pwidth)]

    # the arrays to store the estimated peaks in
    pcent_pix = np.zeros_like(pk,dtype='float')
    wcent_pix = np.zeros_like(pk,dtype='float')

    print(str(len(pk))+' peaks found to center')
    # for each peak, fit a gaussian to find robust center
    for i in range(len(pk)):
        xi = wtemp[pk[i]-pwidth:pk[i]+pwidth*2]
        yi = slice[pk[i]-pwidth:pk[i]+pwidth*2]

        pguess = (np.nanmax(yi), np.median(slice), float(np.nanargmax(yi)), 2.)
        try:
            popt,pcov = curve_fit(pydis._gaus, np.arange(len(xi),dtype='float'), yi,
                                  p0=pguess)
            # the gaussian center of the line in pixel units
            pcent_pix[i] = (pk[i]-pwidth) + popt[2]
            # and the peak in approximate wavelength units
            wcent_pix[i] = xi[np.nanargmax(yi)]

        except RuntimeError:
            print('> autoHeNeAr WARNING: could not center auto-found line')
            # popt = np.array([float('nan'), float('nan'), float('nan'),float('nan')])

            pcent_pix[i] = float('nan')
            wcent_pix[i] = float('nan')

    okcent = np.where((np.isfinite(pcent_pix)))
    pcent_pix = pcent_pix[okcent]
    wcent_pix = wcent_pix[okcent]

    # build observed triangles from HeNeAr file, in wavelength units
    tri_keys, tri_wave = _MakeTris(wcent_pix)

    # make the same observed tri using pixel units.
    # ** should correspond directly **
    _, tri_pix = _MakeTris(pcent_pix)

    # construct the standard object triangles (maybe could be restructured)
    std_keys, std_wave = _BuildLineDict(linelist=linelist)

    # now step thru each observed "tri", see if it matches any in "std"
    # within some tolerance (maybe say 5% for all 3 ratios?)

    # for each observed tri
    for i in range(tri_keys.shape[0]):
        obs = tri_keys[i,:]
        dist = []
        # search over every library tri, find nearest (BRUTE FORCE)
        for j in range(std_keys.shape[0]):
            ref = std_keys[j,:]
            dist.append( np.sum((obs-ref)**2.)**0.5 )

        if (min(dist)<maxdist):
            indx = dist.index(min(dist))
            # replace the observed wavelengths with the catalog values
            tri_wave[i,:] = std_wave[indx,:]
        else:
            # need to do something better here too
            tri_wave[i,:] = np.array([float('nan'), float('nan'), float('nan')])

    ok = np.where((np.isfinite(tri_wave)))

    out_wave = tri_wave[ok]
    out_pix = tri_pix[ok]

    out_wave.sort()
    out_pix.sort()

    if display is True:
        plt.plot()
        plt.scatter(out_pix, out_wave)
        plt.title('autoHeNeAr Find')
        plt.xlabel('Pixel')
        plt.ylabel('Wavelength')
        plt.show()

    return out_pix, out_wave