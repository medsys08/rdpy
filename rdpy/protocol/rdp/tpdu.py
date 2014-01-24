'''
@author: sylvain
'''
from rdpy.network.layer import LayerAutomata
from rdpy.network.type import UInt8, UInt16Le, UInt16Be, UInt32Le, CompositeType, sizeof
from rdpy.network.error import InvalidExpectedDataException
from rdpy.network.const import ConstAttributes, TypeAttributes

@ConstAttributes
@TypeAttributes(UInt8)
class MessageType(object):
    '''
    message type
    '''
    X224_TPDU_CONNECTION_REQUEST = 0xE0
    X224_TPDU_CONNECTION_CONFIRM = 0xD0
    X224_TPDU_DISCONNECT_REQUEST = 0x80
    X224_TPDU_DATA = 0xF0
    X224_TPDU_ERROR = 0x70

@ConstAttributes
@TypeAttributes(UInt8)
class NegociationType(object):
    '''
    negotiation header
    '''
    TYPE_RDP_NEG_REQ = 0x01
    TYPE_RDP_NEG_RSP = 0x02
    TYPE_RDP_NEG_FAILURE = 0x03

@ConstAttributes
@TypeAttributes(UInt32Le)
class Protocols(object):
    '''
    protocols available for TPDU layer
    '''
    PROTOCOL_RDP = 0x00000000
    PROTOCOL_SSL = 0x00000001
    PROTOCOL_HYBRID = 0x00000002
    PROTOCOL_HYBRID_EX = 0x00000008
    
@ConstAttributes
@TypeAttributes(UInt32Le)    
class NegotiationFailureCode(object):
    '''
    protocol negotiation failure code
    '''
    SSL_REQUIRED_BY_SERVER = 0x00000001
    SSL_NOT_ALLOWED_BY_SERVER = 0x00000002
    SSL_CERT_NOT_ON_SERVER = 0x00000003
    INCONSISTENT_FLAGS = 0x00000004
    HYBRID_REQUIRED_BY_SERVER = 0x00000005
    SSL_WITH_USER_AUTH_REQUIRED_BY_SERVER = 0x00000006
    
class TPDUConnectMessage(CompositeType):
    '''
    header of TPDU connection messages 
    '''
    def __init__(self):
        CompositeType.__init__(self)
        self.len = UInt8(lambda:sizeof(self) - 1)
        self.code = UInt8()
        self.padding = (UInt16Be(), UInt16Be(), UInt8())
        #read if there is enought data
        self.protocolNeg = Negotiation(optional = True)
        
class TPDUDataHeader(CompositeType):
    '''
    header send when tpdu exchange application data
    '''
    def __init__(self):
        CompositeType.__init__(self)
        self.header = UInt8(2, constant = True)
        self.messageType = MessageType.X224_TPDU_DATA
        self.separator = UInt8(0x80, constant = True)
    
class Negotiation(CompositeType):
    '''
    negociation request message
    @see: request -> http://msdn.microsoft.com/en-us/library/cc240500.aspx
    @see: response -> http://msdn.microsoft.com/en-us/library/cc240506.aspx
    @see: failure ->http://msdn.microsoft.com/en-us/library/cc240507.aspx
    '''
    def __init__(self, optional = False):
        CompositeType.__init__(self, optional = optional)
        self.code = UInt8()
        self.flag = UInt8(0)
        #always 8
        self.len = UInt16Le(0x0008, constant = True)
        self.selectedProtocol = UInt32Le(conditional = lambda: self.code == NegociationType.TYPE_RDP_NEG_RSP)
        self.failureCode = UInt32Le(conditional = lambda: self.code == NegociationType.TYPE_RDP_NEG_FAILURE)

class TPDU(LayerAutomata):
    '''
    TPDU layer management
    there is an connection automata
    '''
    def __init__(self, presentation = None):
        '''
        Constructor
        @param presentation: MCS layer
        '''
        LayerAutomata.__init__(self, presentation)
        #default selectedProtocol is SSl because is the only supported
        #in this version of RDPY
        #client requested selectedProtocol
        self._requestedProtocol = Protocols.PROTOCOL_SSL
        #server selected selectedProtocol
        self._selectedProtocol = Protocols.PROTOCOL_SSL
    
    def connect(self):
        '''
        connection request
        for client send a connection request packet
        '''
        self.sendConnectionRequest()
    
    def recvConnectionConfirm(self, data):
        '''
        recv connection confirm message
        next state is recvData 
        call connect on presentation layer if all is good
        @param data: Stream that contain connection confirm
        @see: response -> http://msdn.microsoft.com/en-us/library/cc240506.aspx
        @see: failure ->http://msdn.microsoft.com/en-us/library/cc240507.aspx
        '''
        message = TPDUConnectMessage()
        data.readType(message)
        if message.code != MessageType.X224_TPDU_CONNECTION_CONFIRM:
            raise InvalidExpectedDataException("invalid TPDU header code X224_TPDU_CONNECTION_CONFIRM != %d"%message.code)
        #check presence of negotiation response
        if not message.protocolNeg._is_readed:
            raise InvalidExpectedDataException("server must support negotiation protocol to use SSL")
        
        if message.protocolNeg.failureCode._is_readed:
            raise InvalidExpectedDataException("negotiation failure code %x"%message.protocolNeg.failureCode.value)
        
        self._selectedProtocol = message.protocolNeg.selectedProtocol
        
        if self._selectedProtocol != Protocols.PROTOCOL_SSL:
            raise InvalidExpectedDataException("only ssl protocol is supported in RDPY version")
        
        #_transport is TPKT and transport is TCP layer of twisted
        self._transport.transport.startTLS(ClientTLSContext())
        
        self.setNextState(self.recvData)
        #connection is done send to presentation
        LayerAutomata.connect(self)
    
    def recvData(self, data):
        '''
        read data header from packet
        and pass to presentation layer
        @param data: stream
        '''
        header = TPDUDataHeader()
        data.readType(header)
        if header.messageType == MessageType.X224_TPDU_DATA:
            LayerAutomata.recv(self, data)
        elif header.messageType == MessageType.X224_TPDU_ERROR:
            raise Exception("receive error from tpdu layer")
        else:
            raise InvalidExpectedDataException("unknow tpdu code %s"%header.messageType)
        
    def sendConnectionRequest(self):
        '''
        write connection request message
        next state is recvConnectionConfirm
        @see: http://msdn.microsoft.com/en-us/library/cc240500.aspx
        '''
        message = TPDUConnectMessage()
        message.code = MessageType.X224_TPDU_CONNECTION_REQUEST
        message.protocolNeg.code = NegociationType.TYPE_RDP_NEG_REQ
        message.protocolNeg.selectedProtocol = self._requestedProtocol
        self._transport.send(message)
        self.setNextState(self.recvConnectionConfirm)
        
    def send(self, message):
        '''
        write message packet for TPDU layer
        add TPDU header
        '''
        self._transport.send((TPDUDataHeader(), message))
        

#open ssl needed
from twisted.internet import ssl
from OpenSSL import SSL

class ClientTLSContext(ssl.ClientContextFactory):
    '''
    client context factory for open ssl
    '''
    def getContext(self):
        context = SSL.Context(SSL.TLSv1_METHOD)
        context.set_options(0x00020000)#SSL_OP_NO_COMPRESSION
        context.set_options(SSL.OP_DONT_INSERT_EMPTY_FRAGMENTS)
        context.set_options(SSL.OP_TLS_BLOCK_PADDING_BUG)
        return context