package com.steelguard.admin.inspection.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.steelguard.admin.dataset.dto.PageResult;
import com.steelguard.admin.dataset.entity.DatasetImage;
import com.steelguard.admin.dataset.entity.DatasetVersion;
import com.steelguard.admin.dataset.mapper.DatasetImageMapper;
import com.steelguard.admin.dataset.mapper.DatasetVersionMapper;
import com.steelguard.admin.inspection.dto.BatchVO;
import com.steelguard.admin.inspection.dto.CreateDatasetBatchRequest;
import com.steelguard.admin.inspection.entity.InspectBatch;
import com.steelguard.admin.inspection.entity.InspectRecord;
import com.steelguard.admin.inspection.mapper.DefectCaseMapper;
import com.steelguard.admin.inspection.mapper.InspectBatchMapper;
import com.steelguard.admin.inspection.mapper.InspectRecordMapper;
import com.steelguard.common.exception.BusinessException;
import io.minio.MinioClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestClient;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * 质检批次服务测试: 抽样建批校验/落库 与 分页参数收敛
 * (MinIO/RestClient 依赖以 mock 注入, 本类不覆盖异步跑批链路)
 */
@ExtendWith(MockitoExtension.class)
class InspectionServiceTest {

    @Mock private InspectBatchMapper batchMapper;
    @Mock private InspectRecordMapper recordMapper;
    @Mock private DefectCaseMapper caseMapper;
    @Mock private DatasetVersionMapper versionMapper;
    @Mock private DatasetImageMapper datasetImageMapper;
    @Mock private MinioClient minioClient;
    @Mock private MinioClient presignMinioClient;
    @Mock private RestClient aiServiceClient;
    @Mock private RestClient aiServiceTraceClient;
    @Mock private RestClient aiServiceReportClient;

    private InspectionService service;

    @BeforeEach
    void setUp() {
        service = new InspectionService(
                batchMapper, recordMapper, caseMapper, versionMapper, datasetImageMapper,
                minioClient, presignMinioClient,
                aiServiceClient, aiServiceTraceClient, aiServiceReportClient,
                new ObjectMapper());
    }

    private CreateDatasetBatchRequest sampleReq(String... classNames) {
        CreateDatasetBatchRequest req = new CreateDatasetBatchRequest();
        req.setName("测试批次");
        req.setSampleCount(2);
        req.setSeed(42);
        if (classNames.length > 0) {
            req.setClassNames(List.of(classNames));
        }
        return req;
    }

    private DatasetImage image(long id, String name) {
        DatasetImage img = new DatasetImage();
        img.setId(id);
        img.setFileName(name);
        img.setWidth(200);
        img.setHeight(200);
        img.setMinioPath("raw/" + name);
        return img;
    }

    @Test
    void illegalClassNameRejectedBeforeDb() {
        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.createFromDataset(sampleReq("evil_class"), 1L));
        assertEquals(400, ex.getCode());
        verifyNoInteractions(versionMapper, datasetImageMapper, batchMapper);
    }

    @Test
    void missingRawVersionRejected() {
        when(versionMapper.selectOne(any())).thenReturn(null);
        assertThrows(BusinessException.class,
                () -> service.createFromDataset(sampleReq(), 1L));
        verify(batchMapper, never()).insert(any(InspectBatch.class));
    }

    @Test
    void emptySampleRejected() {
        when(versionMapper.selectOne(any())).thenReturn(new DatasetVersion());
        when(datasetImageMapper.selectList(any())).thenReturn(List.of());

        assertThrows(BusinessException.class,
                () -> service.createFromDataset(sampleReq(), 1L));
        verify(batchMapper, never()).insert(any(InspectBatch.class));
    }

    @Test
    void createFromDatasetPersistsBatchAndRecords() {
        DatasetVersion version = new DatasetVersion();
        version.setId(1L);
        when(versionMapper.selectOne(any())).thenReturn(version);
        when(datasetImageMapper.selectList(any())).thenReturn(
                List.of(image(11L, "a.jpg"), image(12L, "b.jpg")));
        // 模拟自增主键回填
        doAnswer(inv -> {
            ((InspectBatch) inv.getArgument(0)).setId(100L);
            return 1;
        }).when(batchMapper).insert(any(InspectBatch.class));

        InspectBatch batch = service.createFromDataset(sampleReq("crazing", "scratches"), 7L);

        assertEquals(100L, batch.getId());
        assertEquals(2, batch.getImageCount());
        assertEquals("dataset", batch.getSource());
        assertEquals(7L, batch.getCreatedBy());
        assertEquals("pending", batch.getStatus());
        verify(batchMapper).insert(any(InspectBatch.class));
        verify(recordMapper, times(2)).insert(any(InspectRecord.class));
    }

    @Test
    @SuppressWarnings("unchecked")
    void pageParamsAreClampedAndResultMapped() {
        // 越界入参: page=0 -> 1, size=999 -> 默认页大小 10
        Page<InspectBatch> page = new Page<>(1, 10);
        InspectBatch b = new InspectBatch();
        b.setId(5L);
        b.setName("批次5");
        b.setStatus("done");
        page.setRecords(List.of(b));
        page.setTotal(1);
        when(batchMapper.selectPage(any(), any())).thenReturn(page);

        PageResult<BatchVO> result = service.pageBatches(0, 999, null);

        ArgumentCaptor<Page<InspectBatch>> pageCaptor = ArgumentCaptor.forClass(Page.class);
        verify(batchMapper).selectPage(pageCaptor.capture(), any());
        assertEquals(1L, pageCaptor.getValue().getCurrent());
        assertEquals(10L, pageCaptor.getValue().getSize());
        assertEquals(1L, result.getTotal());
        assertEquals(1, result.getList().size());
        assertEquals("批次5", result.getList().get(0).getName());
    }
}
