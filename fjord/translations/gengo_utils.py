from functools import wraps

from django.conf import settings

import json
import requests
from gengo import Gengo, GengoError


# Cache of supported languages from Gengo. Theoretically, these don't
# change often, so the first time we request it, we cache it and then
# keep that until the next deployment.
GENGO_LANGUAGE_CACHE = None


class FjordGengoError(Exception):
    """Superclass for all Gengo translation errors"""
    pass


class GengoConfigurationError(FjordGengoError):
    """Raised when the Gengo-centric keys aren't set in settings"""


class GengoUnknownLanguage(FjordGengoError):
    """Raised when the guesser can't guess the language"""


class GengoUnsupportedLanguage(FjordGengoError):
    """Raised when the guesser guesses a language Gengo doesn't support

    .. Note::

       If you buy me a beer, I'll happily tell you how I feel about
       this.

    """


class GengoMachineTranslationFailure(FjordGengoError):
    """Raised when machine translation didn't work"""


def requires_keys(fun):
    """Throw GengoConfigurationError if keys aren't set"""
    @wraps(fun)
    def _requires_keys(self, *args, **kwargs):
        if not self.gengo_api:
            raise GengoConfigurationError()
        return fun(self, *args, **kwargs)
    return _requires_keys


class FjordGengo(object):
    def __init__(self):
        """Constructs a FjordGengo wrapper around the Gengo class

        We do this to make using the API a little easier in the
        context for Fjord as it includes the business logic around
        specific use cases we have.

        Also, having all the Gengo API stuff in one place makes it
        easier for mocking when testing.

        """
        if settings.GENGO_PUBLIC_KEY and settings.GENGO_PRIVATE_KEY:
            gengo_api = Gengo(
                public_key=settings.GENGO_PUBLIC_KEY,
                private_key=settings.GENGO_PRIVATE_KEY
            )
        else:
            gengo_api = None

        self.gengo_api = gengo_api

    @requires_keys
    def get_balance(self):
        """Returns the account balance as a float"""
        balance = self.gengo_api.getAccountBalance()
        return float(balance['response']['credits'])

    @requires_keys
    def get_languages(self):
        """Returns the list of supported language targets

        .. Note::

           This is cached until the next deployment.

        """
        global GENGO_LANGUAGE_CACHE
        if not GENGO_LANGUAGE_CACHE:
            resp = self.gengo_api.getServiceLanguages()
            GENGO_LANGUAGE_CACHE = tuple(
                [item['lc'] for item in resp['response']])
        return GENGO_LANGUAGE_CACHE

    def guess_language(self, text):
        """Guesses the language of the text

        :arg text: text to guess the language of

        :raises GengoUnknownLanguage: if the request wasn't successful
            or the guesser can't figure out which language the text is

        """
        # get_language is a "private API" thing Gengo has, so it's not
        # included in the gengo library and we have to do it manually.
        resp = requests.post(
            'http://api2.gengo.com/api/service/detect/language',
            data=json.dumps({'text': text.encode('utf-8')}),
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            })

        resp_json = resp.json()

        if resp_json['opstat'] == 'ok':
            lang = resp_json['detected_lang_code']
            if lang == 'un':
                raise GengoUnknownLanguage('unknown language')

            if lang not in self.get_languages():
                # If Gengo doesn't support the language, then we might
                # as well throw the guess away because there's not
                # much we can do with it.
                raise GengoUnsupportedLanguage(
                    'unsupported language: {0}'.format(lang))
            return lang

        raise GengoUnknownLanguage('request failure: {0}'.format(resp.content))

    @requires_keys
    def get_machine_translation(self, id_, text):
        """Performs a machine translation through Gengo

        :arg id_: instance id
        :arg text: the text to translate

        :raises GengoUnknownLanguage: if the guesser fails to identify the
            source language of the text

        :raises GengoUnsupportedLanguage: if the guesser guesses a language
            that Gengo doesn't support

        :raises GengoMachineTranslationFailure: if calling machine translation
            fails

        """
        # Note: This will throw GengoUnknownLanguage or
        # GengoUnsupportedLanguage if it fails to guess the language.
        lc_src = self.guess_language(text)

        data = {
            'jobs': {
                'job_1': {
                    'custom_data': str(id_),
                    'body_src': text,
                    'lc_src': lc_src,
                    'lc_tgt': 'en',
                    'tier': 'machine',
                    'type': 'text',
                    'slug': 'Input machine translation',
                }
            }
        }

        try:
            resp = self.gengo_api.postTranslationJobs(
                jobs=data, as_group=0, allow_fork=0)
        except GengoError as ge:
            # It's possible for the guesser to guess a language that's
            # in the list of supported languages, but for some reason
            # it's not actually supported which can throw a 1551
            # GengoError. In that case, we treat it as an unsupported
            # language.
            if ge.error_code == 1551:
                raise GengoUnsupportedLanguage(
                    'unsupported language: {0}'.format(lc_src))
            raise

        if resp['opstat'] == 'ok':
            job = resp['response']['jobs']['job_1']
            if 'body_tgt' not in job:
                raise GengoMachineTranslationFailure('no body_tgt')

            return job['body_tgt']

        raise GengoMachineTranslationFailure(
            'opstat: {0}'.format(resp['opstat']))