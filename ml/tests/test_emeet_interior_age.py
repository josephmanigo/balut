import torch
from ml.balut_ml.train_emeet_age_head import InteriorAge


def test_age_evidence_ignores_the_monitor_and_preserves_cnn_reject_boundary():
    torch.set_num_threads(2)
    net=InteriorAge().eval()
    x=torch.zeros(1,3,224,224)
    outside=x.clone(); outside[:,:,:,:88]=9; outside[:,:,:,136:]=-5; outside[:,:,:36]=2
    torch.testing.assert_close(net.photometry(x),net.photometry(outside),rtol=0,atol=0)
    interior=x.clone(); interior[:,0,76:114,88:136]=2
    assert not torch.equal(net.photometry(x),net.photometry(interior))
    with torch.no_grad(): net.age.weight.zero_(); net.age.bias.fill_(2.)
    scores,embedding=net.combine(torch.zeros(3,16),torch.tensor([[5.,1.,0.],[1.,5.,0.],[1.,3.,4.]]))
    assert scores.argmax(1).tolist()==[1,1,2]
    torch.testing.assert_close(embedding.norm(dim=1),torch.ones(3))
