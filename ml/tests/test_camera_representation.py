import numpy as np
import torch
from balut_ml.search_camera_representation import interior_view,fused,INTERIOR


def test_fixed_interior_excludes_context_and_preserves_uniform_content():
    image=torch.zeros(1,3,224,224)
    left,top,right,bottom=INTERIOR
    image[:,:,top:bottom,left:right]=1
    crop=interior_view(image)
    assert crop.shape==(1,3,224,224)
    torch.testing.assert_close(crop,torch.ones_like(crop))
    outside=image.clone();outside[:,:,:top]=99;outside[:,:,:,:left]=99
    torch.testing.assert_close(interior_view(outside),crop)


def test_fusion_keeps_unit_normalized_features():
    a=np.array([[1.,0.],[0.,1.]],dtype=np.float32)
    b=np.array([[0.,0.,1.],[1.,0.,0.]],dtype=np.float32)
    combined=fused(a,b)
    assert combined.shape==(2,5)
    np.testing.assert_allclose(np.linalg.norm(combined,axis=1),1,atol=1e-6)
