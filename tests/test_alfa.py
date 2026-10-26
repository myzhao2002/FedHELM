import unittest
import numpy as np
from fedhelm.alfa import FEATURES, group_split, sequence_label


class AlfaIsolationTests(unittest.TestCase):
    def test_group_split_never_splits_a_flight(self):
        groups, labels = [], []
        for label in range(6):
            for flight in range(4 if label != 5 else 1):
                groups.extend([f'{label}-{flight}']*3); labels.extend([0,label,label])
        groups, labels = np.array(groups), np.array(labels)
        split = group_split(groups, labels, 631)
        self.assertFalse(set(split['train']) & set(split['test']))
        self.assertFalse(set(split['train']) & set(split['novel']))
        for part in ['train','test']:
            self.assertEqual(set(labels[np.isin(groups,split[part])]), set(range(5)))
        self.assertEqual(split, group_split(groups,labels,631))

    def test_ground_truth_is_not_an_input(self):
        self.assertFalse(any('failure' in x or 'time' in x or 'seq' in x for x in FEATURES))
        self.assertIsNone(sequence_label('carbonZ_no_ground_truth'))
        self.assertEqual(sequence_label('carbonZ_rudder_zero__left_aileron_failure'),5)
        self.assertEqual(sequence_label('carbonZ_both_ailerons_failure'),3)
        self.assertEqual(sequence_label('carbonZ_no_failure'),0)


if __name__=='__main__': unittest.main()
