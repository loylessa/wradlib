# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 09:05:48 2015

@author: heistermann
"""

from osgeo import osr
import wradlib
import pylab as plt
import numpy as np
from matplotlib.path import Path
from matplotlib.collections import PolyCollection
from matplotlib.colors import from_levels_and_colors
from scipy.spatial import cKDTree
import datetime as dt


def mask_from_bbox(x, y, bbox):
    """Return index array based on spatial selection from a bounding box.
    """
    ny, nx = x.shape
    
    ix = np.arange(x.size).reshape(x.shape)

    # Find bbox corners
    #    Plant a tree
    tree = cKDTree(np.vstack((x.ravel(),y.ravel())).transpose())
    # find lower left corner index
    dists, ixll = tree.query([bbox["left"], bbox["bottom"]], k=1)
    ill, jll = np.array(np.where(ix==ixll))[:,0]
    ill = (ixll / nx)-1
    jll = (ixll % nx)-1
    # find lower left corner index
    dists, ixur = tree.query([bbox["right"],bbox["top"]], k=1)
    iur, jur = np.array(np.where(ix==ixur))[:,0]
    iur = (ixur / nx)+1
    jur = (ixur % nx)+1
    
    mask = np.repeat(False, ix.size).reshape(ix.shape)
    if iur>ill:
        mask[ill:iur,jll:jur] = True
        shape = (iur-ill, jur-jll)
    else:
        mask[iur:ill,jll:jur] = True
        shape = (ill-iur, jur-jll)
    
    return mask, shape
        

def points_in_polygon(polygon, points, buffer=0.):
    """Select points inside polygon
    """
    mpath = Path( polygon )
    return  mpath.contains_points(points, radius=-buffer)


def subset_points(pts, bbox, buffer=0.):
    """Subset a large set of points by polygon bbox
    """
    x = pts[:,0]
    y = pts[:,1]
    return np.where(
            (x >= bbox["left"]  -buffer) & \
            (x <= bbox["right"] +buffer) & \
            (y >= bbox["bottom"]-buffer) & \
            (y <= bbox["top"]   +buffer) )[0]
        

def get_bbox(x,y, buffer=0.):
    """Return dictionary of bbox
    """
    return dict(left=np.min(x), 
                right=np.max(x), 
                bottom=np.min(y), 
                top=np.max(y))
    

if __name__ == '__main__':

    # Get RADOLAN grid coordinates
    grid_xy_radolan = wradlib.georef.get_radolan_grid(900, 900)
    x_radolan = grid_xy_radolan[:, :, 0]
    y_radolan = grid_xy_radolan[:, :, 1]
    
    # create radolan projection osr object
    proj_stereo = wradlib.georef.create_osr("dwd-radolan")

    # create Gauss Krueger zone 4 projection osr object
    proj_gk = osr.SpatialReference()
    proj_gk.ImportFromEPSG(31468)

    # transform radolan polar stereographic projection to GK4
    xy = wradlib.georef.reproject(grid_xy_radolan,
                                  projection_source=proj_stereo,
                                  projection_target=proj_gk)

    # Open shapefile (already in GK4)
    shpfile = "data/freiberger_mulde/freiberger_mulde.shp"
    dataset, inLayer = wradlib.io.open_shape(shpfile)
    cats, keys = wradlib.georef.get_shape_coordinates(inLayer, key='GWKZ')

    # Read and prepare the actual data (RADOLAN)
    f = "data/radolan/raa01-sf_10000-1305280050-dwd---bin.gz"
    data, attrs = wradlib.io.read_RADOLAN_composite(f, missing=np.nan)
    sec = attrs['secondary']
    data.flat[sec] = np.nan
    
    # Reduce grid size using a bounding box (for enhancing performance)
    bbox = inLayer.GetExtent()
    buffer = 5000.
    bbox = dict(left=bbox[0]-buffer, right=bbox[1]+buffer, bottom=bbox[2]-buffer, top=bbox[3]+buffer)
    mask, shape = mask_from_bbox(xy[...,0],xy[...,1], bbox)
    xy_ = np.vstack((xy[...,0][mask].ravel(),xy[...,1][mask].ravel())).T
    data_ = data[mask]
    
    ###########################################################################
    # Approach #1a: Assign grid points to each polygon and compute the average.
    # 
    # - Uses matplotlib.path.Path
    # - Each point is weighted equally (assumption: polygon >> grid cell)     
    ###########################################################################

    tstart = dt.datetime.now()    
    
    # Assign points to polygons (we need to do this only ONCE) 
    pips = []  # these are those which we consider inside or close to our polygon
    for cat in cats:
        # Pre-selection to increase performance 
        ixix = points_in_polygon(cat, xy_, buffer=500.)
        if len(ixix)==0:
            # For very small catchments: increase buffer size
            ixix = points_in_polygon(cat, xy_, buffer=1000.)
        pips.append( ixix )
    
    tend = dt.datetime.now()
    print "Approach #1a (assign points) takes: %f seconds" % (tend - tstart).total_seconds()


    ###########################################################################
    # Approach #1b: Assign grid points to each polygon and compute the average
    # 
    # - same as approach #1a, but speed up vai preselecting points using a bbox
    ###########################################################################
    tstart = dt.datetime.now()    
    
    # Assign points to polygons (we need to do this only ONCE) 
    pips = []  # these are those which we consider inside or close to our polygon
    for cat in cats:
        # Pre-selection to increase performance 
        ix = subset_points(xy_, get_bbox(cat[:,0],cat[:,1]), buffer=500.)
        ixix = ix[points_in_polygon(cat, xy_[ix,:], buffer=500.)]
        if len(ixix)==0:
            # For very small catchments: increase buffer size
            ix = subset_points(xy_, get_bbox(cat[:,0],cat[:,1]), buffer=1000.)
            ixix = ix[points_in_polygon(cat, xy_[ix,:], buffer=1000.)]            
        pips.append( ixix )
    
    tend = dt.datetime.now()
    print "Approach #1b (assign points) takes: %f seconds" % (tend - tstart).total_seconds()
    
    # Plot polygons and grid points
    fig = plt.figure(figsize=(10,10))
    ax = fig.add_subplot(111, aspect="equal")
    wradlib.vis.add_lines(ax, cats, color='black', lw=0.5)
    plt.scatter(xy[...,0][mask], xy[...,1][mask], c="blue", edgecolor="None", s=4)
    plt.xlim([bbox["left"]-buffer, bbox["right"]+buffer])
    plt.ylim([bbox["bottom"]-buffer, bbox["top"]+buffer])
    # show associated points for some arbitrarily selected polygons
    for i in xrange(0, len(pips), 15):
        plt.scatter(xy_[pips[i],0], xy_[pips[i],1], c="red", edgecolor="None", s=8)
    plt.tight_layout()
    
        
    tstart = dt.datetime.now()    
    # Now compute the average areal rainfall based on the point assignments
    avg = np.array([])
    for i, cat in enumerate(cats):
        if len(pips[i])>0:
            avg = np.append(avg, np.nanmean(data_.ravel()[pips[i]]) )
        else:
            avg = np.append(avg, np.nan )
            
    # Check if some catchments still are NaN
    invalids = np.where(np.isnan(avg))[0]
    assert len(invalids)==0, "Attention: No average rainfall computed for %d catchments" % len(invalids)

    tend = dt.datetime.now()
    print "Approach #1 (average rainfall) averaging takes: %f seconds" % (tend - tstart).total_seconds()

              
    # Plot average rainfall and original data
    levels = [0,1,2,3,4,5,10,15,20,25,30,40,50,100]
    colors = plt.cm.spectral(np.linspace(0,1,len(levels)) )    
    mycmap, mynorm = from_levels_and_colors(levels, colors, extend="max")

    fig = plt.figure(figsize=(14,8))
    # Average rainfall sum
    ax = fig.add_subplot(121, aspect="equal")
    wradlib.vis.add_lines(ax, cats, color='white', lw=0.5)
    coll = PolyCollection(cats, array=avg, cmap=mycmap, norm=mynorm, edgecolors='none')
    ax.add_collection(coll)
    ax.autoscale()
    cb = plt.colorbar(coll, ax=ax, shrink=0.5)
    cb.set_label("(mm/h)")
    plt.xlabel("GK4 Easting")
    plt.ylabel("GK4 Northing")
    plt.title("Areal average rain sums")
    plt.draw()
    # Original RADOLAN data
    ax1 = fig.add_subplot(122, aspect="equal")
    pm = plt.pcolormesh(xy[:, :, 0], xy[:, :, 1], np.ma.masked_invalid(data), cmap=mycmap, norm=mynorm)
    wradlib.vis.add_lines(ax1, cats, color='white', lw=0.5)
    bbox = inLayer.GetExtent()
    plt.xlim(ax.get_xlim())
    plt.ylim(ax.get_ylim())
    cb = plt.colorbar(pm, ax=ax1, shrink=0.5)
    cb.set_label("(mm/h)")
    plt.xlabel("GK4 Easting")
    plt.ylabel("GK4 Northing")
    plt.title("Original RADOLAN rain sums")
    plt.draw()
    plt.tight_layout()
    
