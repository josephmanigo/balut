import pytest
import torch
from torch import nn
from balut_ml.camera_representation import CameraRepresentation,patch_state,restore_patch


class TinyEncoder(nn.Module):
    def forward(self,x):return nn.functional.normalize(x.mean((2,3)),dim=1)


def test_dual_representation_shares_encoder_and_keeps_unit_norm():
    model=CameraRepresentation("efficient-dual",{"efficient":TinyEncoder()})
    output=model(torch.ones(2,3,224,224))
    assert output.shape==(2,6)
    torch.testing.assert_close(output.norm(dim=1),torch.ones(2))


def test_patch_restores_only_declared_parameters():
    model=nn.Linear(3,2);model.bias.requires_grad_(False)
    original=model.weight.detach().clone();patch=patch_state(model)
    assert set(patch)=={"weight"}
    with torch.no_grad():model.weight.zero_()
    restore_patch(model,patch)
    torch.testing.assert_close(model.weight,original)
    with pytest.raises(ValueError,match="declared training scope"):restore_patch(model,{})
