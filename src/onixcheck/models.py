# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import re
from collections import namedtuple
from defusedxml import lxml
from lxml import etree
from .exeptions import OnixError, get_logger
from . import schema


log = get_logger()


class OnixFile(object):

    def __init__(self, infile):
        self.infile = infile
        self.meta = OnixMeta.from_file(infile)
        if hasattr(infile, 'seek'):
            self.infile.seek(0)

    def xml_tree(self):
        """
        Parse the infile with lxml and add the proper namespace if required.

        :return ElementTree: An lxml ElementTree with proper namespace
        """
        tree = lxml.parse(self.infile)

        if self.meta.namespaces:
            return tree

        log.debug('Adding namespaces to xml for validation')
        root = tree.getroot()
        ns_root = etree.Element(
            tree.docinfo.root_name,
            root.attrib,
            nsmap={None: self.meta.get_ns_string()}
        )
        ns_root[:] = root[:]

        # Roundtrip to add namespace
        doc = lxml.tostring(
            ns_root,
            encoding=tree.docinfo.encoding,
            xml_declaration=True,
            pretty_print=True
        )
        ns_tree = lxml.fromstring(doc)
        return etree.ElementTree(ns_tree)

    def get_validator(self):
        """
        :return etree.XMLSchema:
        """
        return etree.XMLSchema(file=self.meta.get_schema_file())


_BaseMeta = namedtuple('OnixMeta', 'xml_version xml_encoding onix_version onix_style namespaces')


class OnixMeta(_BaseMeta):
    """Read and detect minimal ONIX file properties needed for validation.

    Onix XML files may or may not have `release` and `xmlns` attributes on
    their root element. OnixMeta.from_file(infile) will detect Onix Version
    and Style and also patch the root element with the appropriate namespace
    needed for validation.

    :param str xml_version: XML Version as str ("1.0").
    :param str xml_encoding: XML Encoding as str ("utf-8").
    :param str onix_version: Onix Version as string ("2.1" or "3.0")
    :param str onix_style: Onix Style as str ("short" or "reference")
    :param dict namespaces: dict of str with namspaces from the root element

    """

    V21 = '2.1'
    V30 = '3.0'
    SHORT = 'short'
    REFERENCE = 'reference'

    ONIX_VERSIONS = (V21, V30)
    ONIX_STYLES = (SHORT, REFERENCE)

    SCHEMA_MAP = {
        (V21, SHORT): schema.O21_XSD_SHORT,
        (V21, REFERENCE): schema.O21_XSD_REFERENCE,
        (V30, SHORT): schema.O30_XSD_SHORT,
        (V30, REFERENCE): schema.O30_XSD_REFERENCE
    }

    @classmethod
    def from_tree(cls, tree):
        root = tree.getroot()

        if root.tag.endswith('ONIXmessage'):
            onix_style = cls.SHORT
        elif root.tag.endswith('ONIXMessage'):
            onix_style = cls.REFERENCE
        else:
            raise OnixError('Bad root element: %s' % root.tag)

        onix_version = root.attrib.get('release')
        if onix_version is None:
            log.warning('No release attribute on root element. Try namespace.')
            try:
                if cls.V21 in list(root.nsmap.values())[0]:
                    onix_version = cls.V21
                elif cls.V30 in list(root.nsmap.values())[0]:
                    onix_version = cls.V30
                else:
                    raise OnixError('Could not determin ONIX version.')
            except IndexError:
                raise OnixError('No release attribute and no Namespace :(')

        namespaces = list(root.nsmap.values())
        return cls(
            xml_version=tree.docinfo.xml_version,
            xml_encoding=tree.docinfo.encoding,
            onix_version=onix_version,
            onix_style=onix_style,
            namespaces=namespaces
        )

    @classmethod
    def from_file(cls, infile):
        tree = lxml.parse(infile)
        return cls.from_tree(tree)

    def get_ns_string(self):
        if self.onix_version == self.V21:
            tpl = 'http://www.editeur.org/onix/2.1/%s'
        elif self.onix_version == self.V30:
            tpl = 'http://ns.editeur.org/onix/3.0/%s'
        return tpl % self.onix_style

    def get_schema_file(self):
        return self.SCHEMA_MAP[(self.onix_version, self.onix_style)]


_BaseMessage = namedtuple('Message', 'level validator location message error_type')


class Message(_BaseMessage):

    def __str__(self):
        return ' | '.join(self._asdict().values())

    @classmethod
    def from_logentry(cls, logentry, filename=''):
        """Instanciate ValidationError lxml LogEntry object

        :param _LogEntry logentry: Validatation error from LXML
        :param str filename: Optional filename to prefix error location
        :return ValidationError:
        """
        l = logentry
        location = '%s:%s:%s' % (filename, l.line, l.column)
        message = l.message or ''
        message = re.sub('({.*?})', '', message)

        return cls(
            level=l.level_name,
            validator=l.domain_name,
            location=location,
            message=message,
            error_type=l.type_name
        )
