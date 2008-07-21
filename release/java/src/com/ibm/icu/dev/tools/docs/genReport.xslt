<!--
/*
*******************************************************************************
* Copyright (C) 2008, International Business Machines Corporation and         *
* others. All Rights Reserved.                                                *
*******************************************************************************
* This is the XSLT for the API Report. 
*/
-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<!--
  <xsl:param name="leftStatus" />
  <xsl:param name="rightStatus" />
-->
  <xsl:param name="leftVer" />
  <xsl:param name="rightVer" />
  <xsl:param name="dateTime" />
  <xsl:param name="nul" />

  <xsl:param name="ourYear" />
  

  <xsl:template match="/">
	<xsl:comment>
	 Copyright (C)  <xsl:value-of select="$ourYear" />, International Business Machines Corporation, All Rights Reserved. 
	</xsl:comment>
    <html>
    <head>
    <title>ICU4C API Comparison: <xsl:value-of select="$leftVer"/> with <xsl:value-of select="$rightVer" /> </title>
    <link rel="stylesheet" href="icu4c.css" type="text/css" />
    </head>
    
    <body>
    
    <h1>ICU4C API Comparison: <xsl:value-of select="$leftVer"/> with <xsl:value-of select="$rightVer" /> </h1>
    <hr/>

    <h2>Removed from <xsl:value-of select="$leftVer"/> </h2>
        <xsl:call-template name="genTable">
            <xsl:with-param name="nodes" select="/list/func[@rightStatus=$nul]"/>
        </xsl:call-template>
    <P/><hr/>

    <h2>Deprecated or Obsoleted in <xsl:value-of select="$rightVer" /></h2>
        <xsl:call-template name="genTable">
            <xsl:with-param name="nodes" select="/list/func[(@rightStatus='Deprecated' and @leftStatus!='Deprecated') or (@rightStatus='Obsolete' and @leftStatus!='Obsolete')]"/>
        </xsl:call-template>
    <P/><hr/>

    <h2>Changed in  <xsl:value-of select="$rightVer" /> (old, new)</h2>
        <xsl:call-template name="genTable">
            <xsl:with-param name="nodes" select="/list/func[(@leftStatus != $nul) and (@rightStatus != $nul) and ( (@leftStatus != @rightStatus) or (@leftVersion != @rightVersion) )]"/>
        </xsl:call-template>
    <P/><hr/>

    <h2>Promoted to stable in <xsl:value-of select="$rightVer" /></h2>
        <xsl:call-template name="genTable">
            <xsl:with-param name="nodes" select="/list/func[@leftStatus != 'Stable' and  @rightStatus = 'Stable']"/>
        </xsl:call-template>
    <P/><hr/>
    
    <h2>Added in <xsl:value-of select="$rightVer" /></h2>
        <xsl:call-template name="genTable">
            <xsl:with-param name="nodes" select="/list/func[@leftStatus=$nul]"/>
        </xsl:call-template>
    <P/><hr/>
<!--    
    
-->    

    <p><i><font size="-1">Contents generated by StableAPI tool on <xsl:value-of select="$dateTime" /><br/>Copyright (C) <xsl:value-of select="$ourYear" />, International Business Machines Corporation, All Rights Reserved.</font></i></p>
    </body>
    </html>
  </xsl:template>

  <xsl:template name="genTable">
    <xsl:param name="nodes" />
    <table BORDER="1">
    <THEAD>
        <tr>
            <th> <xsl:value-of select="'File'" /> </th>
            <th> <xsl:value-of select="'API'" /> </th>
            <th> <xsl:value-of select="$leftVer" /> </th>
            <th> <xsl:value-of select="$rightVer" /> </th>
        </tr>
    </THEAD>

        <xsl:for-each select="$nodes">
            <xsl:sort select="@file" />
            
            <tr>
                <xsl:attribute name="class">
                    <xsl:value-of select="'row'"/>
                    <xsl:value-of select="(position() mod 2)"/>
                    <!-- 
                    <xsl:choose>
                        <xsl:when test="(position() mod 2) = 0"><xsl:value-of select="row0" /></xsl:when>
                        <xsl:otherwise><xsl:value-of select="row1" /></xsl:otherwise>
                    </xsl:choose>
                    -->
                </xsl:attribute>
                <td> <xsl:value-of select="@file" /> </td>
                <td> <xsl:value-of select="@prototype" /> </td>
                <td>
                    <xsl:attribute name="class">
                        <xsl:if test ="@leftStatus = 'Stable'">
                                <xsl:value-of select="'stabchange'" />
                        </xsl:if>
                    </xsl:attribute>
                
                    <xsl:value-of select="@leftStatus" />
                    <br/> <xsl:value-of select="@leftVersion" />
                </td>
                <td> <xsl:value-of select="@rightStatus" /> 
                    <br/> 
                    <span>
                        <xsl:attribute name="class">
                            <xsl:if test ="@leftVersion != @rightVersion and @leftVersion != '' and @rightVersion != ''">
                                <xsl:value-of select="'verchange'" />                                
                            </xsl:if>
                        </xsl:attribute>              
                        <span>              
                            <xsl:value-of select="@rightVersion" />
                        </span>
                        <xsl:if test ="@leftVersion != @rightVersion and @leftVersion != '' and @rightVersion != '' and @rightStatus = 'Stable'">
                            <br/><b title='A stable API changed version.' class='bigwarn'>(changed)</b>
                        </xsl:if>
                        <xsl:if test ="@rightStatus = 'Draft' and @rightVersion != $rightVer">
                            <br/><b title='A draft API has the wrong version.' class='bigwarn'>(should be <xsl:value-of select="$rightVer"/>)</b>
                        </xsl:if>
                    </span>
                </td>
            </tr>
        </xsl:for-each>
    </table>
  </xsl:template>
</xsl:stylesheet>




