"""
Basic unit tests for the Fiscal Document Extractor.
"""
import unittest
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import FiscalDocument, Entity, Address, DocumentType, ProcessingStatus
from models.config import CNPJMapper, FilialMapping


class TestModels(unittest.TestCase):
    """Test data models"""
    
    def test_fiscal_document_creation(self):
        """Test creating a fiscal document"""
        doc = FiscalDocument(filename="test.pdf")
        self.assertEqual(doc.filename, "test.pdf")
        self.assertEqual(doc.processing_status, ProcessingStatus.PENDING)
        self.assertEqual(doc.document_type, DocumentType.UNKNOWN)
    
    def test_entity_cnpj_validation(self):
        """Test CNPJ validation and formatting"""
        entity = Entity(cnpj="12345678000190")
        self.assertEqual(entity.cnpj, "12.345.678/0001-90")
    
    def test_address_to_string(self):
        """Test address formatting"""
        address = Address(
            logradouro="Rua Teste",
            numero="123",
            bairro="Centro",
            municipio="São Paulo",
            uf="SP",
            cep="01234-567"
        )
        address_str = address.to_string()
        self.assertIn("Rua Teste", address_str)
        self.assertIn("123", address_str)
        self.assertIn("São Paulo/SP", address_str)


class TestCNPJMapper(unittest.TestCase):
    """Test CNPJ mapping functionality"""
    
    def setUp(self):
        """Create a temporary mapping file"""
        self.test_mapping = {
            "12.345.678/0001-90": {
                "coligada": "1",
                "filial": "01",
                "nome": "Test Company"
            }
        }
        
        # Create temp file
        import json
        import tempfile
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(self.test_mapping, self.temp_file)
        self.temp_file.close()
        
        self.mapper = CNPJMapper(Path(self.temp_file.name))
    
    def tearDown(self):
        """Clean up temp file"""
        Path(self.temp_file.name).unlink()
    
    def test_lookup_existing_cnpj(self):
        """Test looking up an existing CNPJ"""
        result = self.mapper.lookup("12.345.678/0001-90")
        self.assertIsNotNone(result)
        self.assertEqual(result.coligada, "1")
        self.assertEqual(result.filial, "01")
    
    def test_lookup_nonexistent_cnpj(self):
        """Test looking up a non-existent CNPJ"""
        result = self.mapper.lookup("99.999.999/9999-99")
        self.assertIsNone(result)
    
    def test_cnpj_normalization(self):
        """Test CNPJ normalization (with/without formatting)"""
        result1 = self.mapper.lookup("12.345.678/0001-90")
        result2 = self.mapper.lookup("12345678000190")
        self.assertEqual(result1, result2)


if __name__ == '__main__':
    unittest.main()
