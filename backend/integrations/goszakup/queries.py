"""
GosZakup GraphQL query definitions.
API docs: https://goszakup.gov.kz/ru/opendata/index
Schema explorer: https://ows.goszakup.gov.kz/app/graphql
"""

# ── Fetch published tender announcements ─────────────────────────────────────
QUERY_ANNOUNCES = """
query GetAnnounces($limit: Int!, $offset: Int!, $filter: AnnouncesFiltersInput) {
  Announces(limit: $limit, offset: $offset, filter: $filter) {
    id
    numberAnno
    nameRu
    nameKz
    nameEn
    publishDate
    endDate
    statusId
    refBuyWay {
      id
      nameRu
    }
    summ
    customerBin
    customer {
      bin
      nameRu
      address
      region {
        nameRu
      }
    }
    Lots {
      id
      nameRu
      nameKz
      descriptionRu
      count
      amount
      refUnit {
        nameRu
        code
      }
      Files {
        id
        nameRu
        filePath
        size
        extension
      }
      trdBuy {
        id
        numberTrdBuy
        statusId
        endDate
        summ
      }
    }
    Files {
      id
      nameRu
      filePath
      extension
    }
  }
}
"""

# ── Fetch a single announcement with full lot details ────────────────────────
QUERY_ANNOUNCE_BY_ID = """
query GetAnnounceById($id: Int!) {
  Announces(filter: { id: $id }) {
    id
    numberAnno
    nameRu
    nameKz
    publishDate
    endDate
    statusId
    summ
    customerBin
    customer {
      bin
      nameRu
      address
    }
    Lots {
      id
      nameRu
      descriptionRu
      count
      amount
      refUnit {
        nameRu
        code
      }
      Files {
        id
        nameRu
        filePath
        extension
      }
    }
    Files {
      id
      nameRu
      filePath
      extension
    }
  }
}
"""

# ── Fetch lots directly ───────────────────────────────────────────────────────
QUERY_LOTS = """
query GetLots($limit: Int!, $offset: Int!, $announce_id: Int) {
  Lots(limit: $limit, offset: $offset, filter: { announce_id: $announce_id }) {
    id
    nameRu
    nameKz
    descriptionRu
    count
    amount
    refUnit {
      nameRu
      code
    }
    announce {
      id
      numberAnno
      nameRu
      publishDate
      endDate
      statusId
      summ
      customerBin
      customer {
        nameRu
        bin
      }
    }
    Files {
      id
      nameRu
      filePath
      extension
    }
  }
}
"""

# GosZakup status IDs
STATUS_PUBLISHED = 2
STATUS_DRAFT = 1
STATUS_FINISHED = 3
STATUS_CANCELLED = 4

# GosZakup buy way IDs (procurement method)
BUY_WAY_OPEN_TENDER = 2
BUY_WAY_OPEN_CONTEST = 4
BUY_WAY_SINGLE_SOURCE = 5
BUY_WAY_PRICE_OFFERS = 6
BUY_WAY_SHORT_LIST = 7
