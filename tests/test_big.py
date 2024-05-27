import numpy as np
import pytest

from csbdeep.utils import normalize
from stardist.matching import matching, relabel_sequential
from stardist import calculate_extents, polyhedron_to_label
from utils import real_image2d, real_image3d

from stardist.geometry import polygons_to_label_coord
from stardist.big import Block, BlockND, Polygon, Polyhedron



def render_polygons(polys, shape):
    return polygons_to_label_coord(polys['coord'], shape=shape)



def repeat(mask, reps):
    if np.isscalar(reps):
        reps = (reps,) * mask.ndim
    def shift(mask, v):
        _mask = mask.copy()
        _mask[_mask>0] += v
        return _mask
    _shift = shift if np.issubdtype(mask.dtype, np.integer) else (lambda x, *args: x)
    for d,rep in enumerate(reps):
        n_labels = mask.max()
        mask = [_shift(mask, n_labels*i) for i in range(rep)]
        mask = np.concatenate(mask, axis=d)
    return mask



def reassemble(lbl, axes, block_size, min_overlap, context, grid):
    blocks = BlockND.cover(lbl.shape, axes=axes, block_size=block_size, min_overlap=min_overlap, context=context, grid=grid)
    # print(len(blocks))
    result = np.zeros_like(lbl)

    for block in blocks:
        x = block.read(lbl)
        x = block.crop_context(x)
        x = block.filter_objects(x, polys=None)
        block.write(result, x)

    assert np.all(lbl == result)



@pytest.mark.parametrize('grid', [1, 3, 6])
@pytest.mark.parametrize('block_size, context', [(40,0), (55,3), (80,10), (128,17), (256,80), (512,93)])
def test_cover2D(block_size, context, grid):
    lbl = real_image2d()[1]
    lbl = lbl.astype(np.int32)

    max_sizes = tuple(calculate_extents(lbl, func=np.max))
    min_overlap = tuple(1+v for v in max_sizes)
    lbl = repeat(lbl, 4)
    assert max_sizes == tuple(calculate_extents(lbl, func=np.max))

    reassemble(lbl, 'YX', block_size, min_overlap, context, grid)



@pytest.mark.parametrize('grid', [1, 3])
@pytest.mark.parametrize('block_size, context', [((33,71,64),3), ((48,96,96),0), ((62,97,93),(0,11,9))])
def test_cover3D(block_size, context, grid):
    lbl = real_image3d()[1]
    lbl = lbl.astype(np.int32)

    max_sizes = tuple(calculate_extents(lbl, func=np.max))
    min_overlap = tuple(1+v for v in max_sizes)
    lbl = repeat(lbl, (2,4,4))
    assert max_sizes == tuple(calculate_extents(lbl, func=np.max))

    reassemble(lbl, 'ZYX', block_size, min_overlap, context, grid)


def test_edgecases():
    # in some cases need to add extra context to prevent overlapping write regions of non-neighboring blocks
    # cf. https://forum.image.sc/t/trouble-using-stardist-predict-instances-big/88871/6
    for size in range(7800,8000):
        Block.cover(size=size, block_size=4096, min_overlap=128, context=128, grid=16)


@pytest.mark.parametrize('use_channel', [False, True])
def test_predict2D(model2d, use_channel):
    model = model2d
    img = real_image2d()[0]
    img = normalize(img, 1, 99.8)
    img = repeat(img, 2)
    axes = 'YX'

    if use_channel:
        img = img[...,np.newaxis]
        axes += 'C'

    ref_labels, ref_polys = model.predict_instances(img, axes=axes)
    res_labels, res_polys = model.predict_instances_big(img, axes=axes, block_size=288, min_overlap=32, context=96)

    m = matching(ref_labels, res_labels, thresh=0.99)
    assert (1.0, 1.0) == (m.accuracy, m.mean_true_score)

    m = matching(render_polygons(ref_polys, shape=img.shape),
                 render_polygons(res_polys, shape=img.shape), thresh=0.99)
    assert (1.0, 1.0) == (m.accuracy, m.mean_true_score)

    # sort them first lexicographic
    ref_inds = np.lexsort(ref_polys["points"].T)
    res_inds = np.lexsort(res_polys["points"].T)

    assert np.allclose(ref_polys["coord"][ref_inds],
                       res_polys["coord"][res_inds],atol=1e-2)
    assert np.allclose(ref_polys["points"][ref_inds],
                       res_polys["points"][res_inds],atol=1e-2)
    assert np.allclose(ref_polys["prob"][ref_inds],
                       res_polys["prob"][res_inds],atol=1e-2)

    return ref_polys, res_polys



def test_predict3D(model3d):
    model = model3d
    img = real_image3d()[0]
    img = normalize(img, 1, 99.8)
    img = repeat(img, 2)

    ref_labels, ref_polys = model.predict_instances(img)
    res_labels, res_polys = model.predict_instances_big(img, axes='ZYX', block_size=(55,105,105), min_overlap=(13,25,25), context=(17,30,30))

    m = matching(ref_labels, res_labels, thresh=0.99)
    # 2024-01-25: failed on github actions: "windows-latest" in combination with tensorflow 2.15.0 (python 3.9, 3.10, and 3.11)
    #             (m.mean_true_score was 0.9999979271079009)
    # assert (1.0, 1.0) == (m.accuracy, m.mean_true_score)
    assert m.accuracy == 1.0 and m.mean_true_score > 0.999

    # sort them first lexicographic
    ref_inds = np.lexsort(ref_polys["points"].T)
    res_inds = np.lexsort(res_polys["points"].T)

    assert np.allclose(ref_polys["dist"][ref_inds],
                       res_polys["dist"][res_inds],atol=1e-2)
    assert np.allclose(ref_polys["points"][ref_inds],
                       res_polys["points"][res_inds],atol=1e-2)
    assert np.allclose(ref_polys["prob"][ref_inds],
                       res_polys["prob"][res_inds],atol=1e-2)

    return ref_polys, res_polys



# def test_repaint2D(model2d):
#     np.random.seed(42)
#     model = model2d
#     img = real_image2d()[0]
#     img = normalize(img, 1, 99.8)

#     # get overlapping polygon predictions, wiggle them a bit, render reference label image
#     polys = model.predict_instances(img, nms_thresh=0.97)[1]
#     polys['coord'] += np.random.normal(scale=3, size=polys['coord'].shape[:2]+(1,))
#     labels = render_polygons(polys, img.shape)

#     # shuffle polygon probabilities/scores and render label image
#     polys2 = {k:v.copy() for k,v in polys.items()}
#     np.random.shuffle(polys2['prob'])
#     labels2 = render_polygons(polys2, img.shape)
#     assert not np.all(labels == labels2)

#     # repaint all labels (which are visible in the reference label image)
#     repaint_ids = set(np.unique(labels)) - {0}
#     repaint_labels(labels2, list(repaint_ids), polys)
#     assert np.all(labels == labels2)



# def test_repaint3D(model3d):
#     np.random.seed(42)
#     model = model3d
#     img = real_image3d()[0]
#     img = normalize(img, 1, 99.8)

#     # get overlapping polygon predictions, wiggle them a bit, render reference label image
#     polys = model.predict_instances(img, nms_thresh=0.95)[1]
#     polys['dist'] += np.random.normal(scale=3, size=polys['dist'].shape[:1]+(1,))
#     polys['dist'] = np.maximum(1, polys['dist'])
#     labels = polyhedron_to_label(polys['dist'], polys['points'], polys['rays'], img.shape, prob=polys['prob'])

#     # shuffle polygon probabilities/scores and render label image
#     polys2 = {k:v.copy() if isinstance(v,np.ndarray) else v for k,v in polys.items()}
#     np.random.shuffle(polys2['prob'])
#     labels2 = polyhedron_to_label(polys2['dist'], polys2['points'], polys2['rays'], img.shape, prob=polys2['prob'])
#     assert np.count_nonzero(labels != labels2) > 10000

#     # repaint all labels (which are visible in the reference label image)
#     repaint_ids = set(np.unique(labels)) - {0}
#     repaint_labels(labels2, list(repaint_ids), polys)
#     assert np.count_nonzero(labels != labels2) < 10 # TODO: why not 0?



def test_polygon_order_2D(model2d):
    model = model2d
    img = real_image2d()[0]
    img = normalize(img, 1, 99.8)
    labels, polys = model.predict_instances(img, nms_thresh=0)

    for i,coord in enumerate(polys['coord'], start=1):
        # polygon representing object with id i
        p = Polygon(coord, shape_max=labels.shape)
        # mask of object with id i in label image (not occluded since nms_thresh=0)
        mask_i = labels[p.slice] == i
        assert np.all(p.mask == mask_i)



def test_polyhedron_order_3D(model3d):
    model = model3d
    img = real_image3d()[0]
    img = normalize(img, 1, 99.8)
    labels, polys = model.predict_instances(img, nms_thresh=0)

    for i,(dist,point) in enumerate(zip(polys['dist'],polys['points']), start=1):
        # polygon representing object with id i
        p = Polyhedron(dist, point, polys['rays'], shape_max=labels.shape)
        # mask of object with id i in label image (not occluded since nms_thresh=0)
        mask_i = labels[p.slice] == i
        # assert np.all(p.mask == mask_i) # few pixels are sometimes different, why?
        frac_same = np.count_nonzero(p.mask == mask_i) / p.mask.size
        assert frac_same > 0.99



if __name__ == '__main__':
    from conftest import _model2d
    # test_polygon_order_2D(_model2d())

    a,b = test_predict2D(_model2d(), use_channel=False)
