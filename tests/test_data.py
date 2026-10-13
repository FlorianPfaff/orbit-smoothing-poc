import numpy as np
import pytest
from orbit_poc.data import Dataset,save_dataset,load_dataset,subset_observations

def test_roundtrip_excludes_truth(tmp_path):
    data=Dataset(np.array([0.,60.]),{'node':np.array([0,1]),'station_pos':np.ones((2,3)),
        'station_vel':np.zeros((2,3)),'y':np.ones((2,2)),'sigma':np.array([10.,.01])},np.ones(6),np.ones(6),{'purpose':'test'})
    path=save_dataset(data,tmp_path)
    restored=load_dataset(path)
    np.testing.assert_array_equal(restored.observations['y'],data.observations['y'])
    with np.load(path) as f:
        assert 'truth' not in f.files and 'states' not in f.files
    assert len(subset_observations(data,[True,False]).observations['node'])==1

def test_reject_invalid_node_indices():
    with pytest.raises(ValueError,match='outside trajectory'):
        Dataset(np.array([0.,60.]),{'node':np.array([3]),'station_pos':np.ones((1,3)),
            'station_vel':np.zeros((1,3)),'y':np.ones((1,2)),'sigma':np.array([10.,.01])},np.ones(6),np.ones(6))
