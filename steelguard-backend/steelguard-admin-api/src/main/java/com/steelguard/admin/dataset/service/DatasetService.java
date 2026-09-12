package com.steelguard.admin.dataset.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.steelguard.admin.dataset.dto.DatasetEdaVO;
import com.steelguard.admin.dataset.dto.DatasetImageVO;
import com.steelguard.admin.dataset.dto.PageResult;
import com.steelguard.admin.dataset.entity.DatasetImage;
import com.steelguard.admin.dataset.entity.DatasetVersion;
import com.steelguard.admin.dataset.mapper.DatasetImageMapper;
import com.steelguard.admin.dataset.mapper.DatasetVersionMapper;
import com.steelguard.common.exception.BusinessException;
import io.minio.GetPresignedObjectUrlArgs;
import io.minio.MinioClient;
import io.minio.http.Method;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * 数据集查询服务: 版本列表 / EDA 统计 / 图片分页(MinIO 预签名)
 */
@Slf4j
@Service
public class DatasetService {

    private final DatasetVersionMapper versionMapper;
    private final DatasetImageMapper imageMapper;
    /** 预签名专用客户端(对外端点); 本服务只读不写, 用它签名浏览器可直达的 URL */
    private final MinioClient presignMinioClient;

    public DatasetService(DatasetVersionMapper versionMapper,
                          DatasetImageMapper imageMapper,
                          @Qualifier("presignMinioClient") MinioClient presignMinioClient) {
        this.versionMapper = versionMapper;
        this.imageMapper = imageMapper;
        this.presignMinioClient = presignMinioClient;
    }

    @Value("${minio.datasets-bucket:datasets}")
    private String datasetsBucket;

    /** 全部版本(新 -> 旧) */
    public List<DatasetVersion> listVersions() {
        return versionMapper.selectList(
                new LambdaQueryWrapper<DatasetVersion>().orderByDesc(DatasetVersion::getId));
    }

    /** EDA 统计; versionId 为空时取最新版本 */
    public DatasetEdaVO getEda(Long versionId) {
        DatasetVersion version = resolveVersion(versionId);

        long totalImages = imageMapper.selectCount(
                new LambdaQueryWrapper<DatasetImage>()
                        .eq(DatasetImage::getVersionId, version.getId()));

        Map<String, Object> bboxSize = imageMapper.selectBboxSize(version.getId());
        Object totalBboxesObj = bboxSize.get("totalBboxes");
        long totalBboxes = totalBboxesObj == null ? 0L : ((Number) totalBboxesObj).longValue();

        DatasetEdaVO vo = new DatasetEdaVO();
        vo.setVersionId(version.getId());
        vo.setVersion(version.getVersion());
        vo.setStatus(version.getStatus());
        vo.setTotalImages(totalImages);
        vo.setTotalAnnotations(totalBboxes);
        vo.setAvgBboxesPerImage(totalImages == 0 ? 0.0
                : Math.round(totalBboxes * 100.0 / totalImages) / 100.0);
        vo.setClassDistribution(imageMapper.selectClassDistribution(version.getId()));
        vo.setBboxPerImageDistribution(imageMapper.selectBboxPerImage(version.getId()));
        vo.setAugmentMethodDistribution(imageMapper.selectMethodDistribution(version.getId()));
        vo.setImageSize(parseImageSize(imageMapper.selectImageSize(version.getId())));
        vo.setBboxSize(bboxSize);
        return vo;
    }

    /** 图片分页查询, 每条带 MinIO 预签名 URL */
    public PageResult<DatasetImageVO> pageImages(Long versionId, String className, String split,
                                                 long page, long size) {
        DatasetVersion version = resolveVersion(versionId);
        if (page < 1) {
            page = 1;
        }
        if (size < 1 || size > 100) {
            size = 12;
        }

        LambdaQueryWrapper<DatasetImage> qw = new LambdaQueryWrapper<DatasetImage>()
                .eq(DatasetImage::getVersionId, version.getId())
                .eq(StringUtils.hasText(className), DatasetImage::getClassName, className)
                .eq(StringUtils.hasText(split), DatasetImage::getSplit, split)
                .orderByAsc(DatasetImage::getId);

        Page<DatasetImage> pg = imageMapper.selectPage(new Page<>(page, size), qw);

        List<DatasetImageVO> list = new ArrayList<>();
        for (DatasetImage img : pg.getRecords()) {
            DatasetImageVO vo = new DatasetImageVO();
            vo.setId(img.getId());
            vo.setFileName(img.getFileName());
            vo.setClassName(img.getClassName());
            vo.setWidth(img.getWidth());
            vo.setHeight(img.getHeight());
            vo.setSplit(img.getSplit());
            vo.setAugmentMethod(img.getAugmentMethod());
            vo.setFileSize(img.getFileSize());
            vo.setUrl(presignedUrl(img.getMinioPath()));
            list.add(vo);
        }
        return new PageResult<>(pg.getTotal(), page, size, list);
    }

    /** versionId 为空取最新版本; 不存在抛业务异常 */
    private DatasetVersion resolveVersion(Long versionId) {
        DatasetVersion version;
        if (versionId == null) {
            version = versionMapper.selectOne(
                    new LambdaQueryWrapper<DatasetVersion>()
                            .orderByDesc(DatasetVersion::getId)
                            .last("LIMIT 1"));
        } else {
            version = versionMapper.selectById(versionId);
        }
        if (version == null) {
            throw new BusinessException(40401, "数据集版本不存在: " + versionId);
        }
        return version;
    }

    /** 图像尺寸: depths "1,3" -> [1,3], 其余键原样保留 */
    private Map<String, Object> parseImageSize(Map<String, Object> row) {
        if (row == null) {
            return Map.of();
        }
        Object depths = row.get("depths");
        if (depths != null) {
            List<Integer> depthList = Arrays.stream(depths.toString().split(","))
                    .map(String::trim)
                    .filter(StringUtils::hasText)
                    .map(Integer::valueOf)
                    .toList();
            row.put("depths", depthList);
        }
        return row;
    }

    private String presignedUrl(String minioPath) {
        if (!StringUtils.hasText(minioPath)) {
            return null;
        }
        try {
            return presignMinioClient.getPresignedObjectUrl(
                    GetPresignedObjectUrlArgs.builder()
                            .method(Method.GET)
                            .bucket(datasetsBucket)
                            .object(minioPath)
                            .expiry(1, TimeUnit.HOURS)
                            .build());
        } catch (Exception e) {
            log.warn("生成预签名 URL 失败 {}: {}", minioPath, e.getMessage());
            return null;
        }
    }
}
