import time

from django.conf import settings

from nose import SkipTest
from pyelasticsearch.exceptions import (Timeout, ConnectionError,
                                        ElasticHttpNotFoundError)
from test_utils import TestCase

from fjord.base.tests import with_save
from fjord.search.index import get_index, get_indexing_es
from fjord.search.models import Record


class ElasticTestCase(TestCase):
    """Base class for Elastic Search tests, providing some conveniences"""
    skipme = False

    @classmethod
    def setUpClass(cls):
        super(ElasticTestCase, cls).setUpClass()

        if not getattr(settings, 'ES_URLS', None):
            cls.skipme = True
            return

        # try to connect to ES and if it fails, skip ElasticTestCases.
        try:
            get_indexing_es().health()
        except (Timeout, ConnectionError):
            cls.skipme = True
            return

        cls._old_es_index_prefix = settings.ES_INDEX_PREFIX
        settings.ES_INDEX_PREFIX = settings.ES_INDEX_PREFIX + 'test'

    @classmethod
    def tearDownClass(cls):
        super(ElasticTestCase, cls).tearDownClass()
        if not cls.skipme:
            # Restore old setting.
            settings.ES_INDEX_PREFIX = cls._old_es_index_prefix

    def setUp(self):
        if self.skipme:
            raise SkipTest

        super(ElasticTestCase, self).setUp()
        self.setup_indexes()

    def tearDown(self):
        super(ElasticTestCase, self).tearDown()
        self.teardown_indexes()

    def refresh(self, timesleep=0):
        index = get_index()

        # Any time we're doing a refresh, we're making sure that the
        # index is ready to be queried.  Given that, it's almost
        # always the case that we want to run all the generated tasks,
        # then refresh.
        # TODO: uncomment this when we have live indexing.
        # generate_tasks()

        get_indexing_es().refresh(index)
        if timesleep > 0:
            time.sleep(timesleep)

    def setup_indexes(self, empty=False):
        """(Re-)create ES indexes."""
        from fjord.search.index import es_reindex_cmd

        if empty:
            # Removes the index and creates a new one with nothing in
            # it (by abusing the percent argument).
            es_reindex_cmd(percent=0)
        else:
            # Removes the index, creates a new one, and indexes
            # existing data into it.
            es_reindex_cmd()

        self.refresh(settings.ES_TEST_SLEEP_DURATION)

    def teardown_indexes(self):
        es = get_indexing_es()
        try:
            es.delete_index(get_index())
        except ElasticHttpNotFoundError:
            # If we get this error, it means the index didn't exist
            # so there's nothing to delete.
            pass


@with_save
def record(**kwargs):
    """Model maker for fjord.search.models.Record."""
    defaults = {
        'batch_id': 'ou812',
        'name': 'Frank'
        }
    defaults.update(kwargs)
    return Record(**defaults)
